"""
Runner with graceful shutdown.

https://github.com/mikeshardmind/salamander-reloaded/blob/637eef77c2c3f7b26a94639265ef70721e6f1729/src/salamander/runner.py#L50
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import signal
import socket
import threading

import discord
from async_utils.sig_service import SignalService, SpecialExit

from . import _type_shim as t
from ._type import HasExports
from .utils.files import get_token
from .utils.logs import with_logging

log = logging.getLogger(__name__)


def _run_bot(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[signal.Signals]) -> None:
    loop.set_task_factory(asyncio.eager_task_factory)
    asyncio.set_event_loop(loop)

    from . import identicon, useful

    initial_exts: list[HasExports] = [useful, identicon]

    from .bot import Dynamo

    intents = discord.Intents.default()
    intents.members = True
    intents.guild_scheduled_events = True
    client = Dynamo(intents=intents, initial_exts=initial_exts)

    async def bot_entry_point() -> None:
        try:
            async with client:
                await client.start(get_token())
        finally:
            if not client.is_closed():
                await client.close()

    async def sig_handler() -> None:
        sig = await queue.get()
        if sig != SpecialExit.EXIT:
            log.info("Shutting down, received signal %r", sig)
        loop.call_soon(loop.stop)

    async def entry_point() -> None:
        t_bot = asyncio.create_task(bot_entry_point())
        t_sig = asyncio.create_task(sig_handler())
        await asyncio.gather(t_bot, t_sig)

    def stop_when_done(fut: asyncio.Future[None]) -> None:
        loop.stop()

    fut = asyncio.ensure_future(entry_point(), loop=loop)
    try:
        fut.add_done_callback(stop_when_done)
        loop.run_forever()
    finally:
        fut.remove_done_callback(stop_when_done)
        if not client.is_closed():
            # give the client a brief opportunity to close
            _close_task = loop.create_task(client.close())
        loop.run_until_complete(asyncio.sleep(0.001))

        tasks: set[asyncio.Task[t.Any]] = {t for t in asyncio.all_tasks(loop) if not t.done()}

        async def limited_finalization():
            _done, pending = await asyncio.wait(tasks, timeout=0.1)
            if not pending:
                log.debug("Clean shutdown accomplished.")
                return

            for task in tasks:
                task.cancel()

            _done, pending = await asyncio.wait(tasks, timeout=0.1)

            for task in pending:
                name = task.get_name()
                coro = task.get_coro()
                log.warning("Task %s wrapping coro %r did not exit properly", name, coro)

        if tasks:
            loop.run_until_complete(limited_finalization())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())

        for task in tasks:
            try:
                if (exc := task.exception()) is not None:
                    loop.call_exception_handler({
                        "message": "Unhandled exception in task during shutdown.",
                        "exception": exc,
                        "task": task,
                    })
            except (asyncio.InvalidStateError, asyncio.CancelledError):
                pass

        asyncio.set_event_loop(None)
        loop.close()

        if not fut.cancelled():
            fut.result()


def _wrapped_run_bot(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[signal.Signals],
    socket: socket.socket,
):
    try:
        _run_bot(loop, queue)
    finally:
        socket.send(SpecialExit.EXIT.to_bytes())


def run_bot() -> None:
    gc.set_threshold(0)

    with with_logging():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[signal.Signals | SpecialExit] = asyncio.Queue()

        def _stop_loop_on_signal(s: signal.Signals | SpecialExit) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, s)

        signal_service = SignalService()
        sock = signal_service.get_send_socket()

        bot_thread = threading.Thread(target=_wrapped_run_bot, args=(loop, queue, sock))

        signal_service.add_startup(bot_thread.start)
        signal_service.add_signal_cb(_stop_loop_on_signal)
        signal_service.add_join(bot_thread.join)

        signal_service.run()

    os._exit(0)
