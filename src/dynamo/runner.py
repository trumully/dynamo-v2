"""
This code is adapted from https://github.com/mikeshardmind/salamander-reloaded/blob/c2c104e78d62d676fe9c93eb70ff1b1c150f798c/src/salamander/runner.py
Copyright and license is preserved in compliance with MPLv2

This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

__lazy_modules__: list[str] = ["asyncio"]

import asyncio
import gc
import os
import signal
import socket
import threading
from pathlib import Path

import aiohttp
import apsw
import apsw.bestpractice
import discord
from async_utils.sig_service import SignalService, SpecialExit

from . import _typings as t
from ._types import HasExports
from .logs import Logger, get_logger, with_logging
from .utils import dirs, get_token, to_json

log: Logger = get_logger(__name__)

DB_PATH = str(dirs.user_data_path / "dynamo.db")


def _run_bot(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[signal.Signals | SpecialExit]) -> None:
    loop.set_task_factory(asyncio.eager_task_factory)
    asyncio.set_event_loop(loop)

    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    intents.presences = True
    # needed for consistent scheduled event fetching
    # otherwise any created / deleted events are not added or removed as expected.
    intents.guild_scheduled_events = True

    connector = aiohttp.TCPConnector(
        happy_eyeballs_delay=None,
        family=socket.AddressFamily.AF_INET,
        ttl_dns_cache=60,
        loop=loop,
    )
    session = aiohttp.ClientSession(connector=connector, json_serialize=to_json)

    from . import identicon, pins, useful

    initial_exts: list[HasExports] = [identicon, pins, useful]

    from .bot import Dynamo

    read_conn = apsw.Connection(DB_PATH, flags=apsw.SQLITE_OPEN_READONLY)
    rw_conn = apsw.Connection(DB_PATH)

    client = Dynamo(
        intents=intents,
        session=session,
        conn=rw_conn,
        read_conn=read_conn,
        initial_exts=initial_exts,
        connector=connector,
    )

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
            log.info("Shutting down, received signal: %r", sig)
        loop.call_soon(loop.stop)

    async def entry_point() -> None:
        t_bot = asyncio.create_task(bot_entry_point())
        t_sig = asyncio.create_task(sig_handler())
        await asyncio.gather(t_bot, t_sig)

    def stop_when_done(_fut: asyncio.Future[None]) -> None:
        loop.stop()

    fut = asyncio.ensure_future(entry_point(), loop=loop)
    try:
        fut.add_done_callback(stop_when_done)
        loop.run_forever()
    finally:
        fut.remove_done_callback(stop_when_done)
        if not client.is_closed():
            _close_task = loop.create_task(client.close())
        loop.run_until_complete(asyncio.sleep(0.001))

        tasks: set[asyncio.Task[t.Any]] = {t for t in asyncio.all_tasks(loop) if not t.done()}

        async def limited_finalization() -> None:
            _done, pending = await asyncio.wait(tasks, timeout=0.1)
            if not pending:
                log.debug("Clean shutdown accomplished")
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
            except asyncio.InvalidStateError, asyncio.CancelledError:
                pass

        asyncio.set_event_loop(None)
        loop.close()

        if not fut.cancelled():
            fut.result()

        read_conn.close()
        rw_conn.pragma("analysis_limit", 400)
        rw_conn.pragma("optimize")
        rw_conn.close()


def _wrapped_run_bot(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[signal.Signals | SpecialExit],
    socket: socket.socket,
):
    try:
        _run_bot(loop, queue)
    finally:
        socket.send(SpecialExit.EXIT.to_bytes())


def ensure_schema() -> None:
    conn = apsw.Connection(DB_PATH)

    schema_path = (Path(__file__)).with_name("schema.sql")
    with schema_path.open("r") as f:
        to_exec: list[str] = []
        for line in f.readlines():
            text = line.strip()
            if not text.startswith("--"):
                to_exec.append(text)

    iterator = iter(to_exec)
    for line in iterator:
        s = [line]
        while n := next(iterator, None):
            s.append(n)
        statement = "\n".join(s)
        list(conn.execute(statement))

    conn.close()


def run_bot() -> None:
    gc.set_threshold(0)

    def conn_hook(connection: apsw.Connection):
        for hook in (
            apsw.bestpractice.connection_wal,
            apsw.bestpractice.connection_busy_timeout,
            apsw.bestpractice.connection_enable_foreign_keys,
            apsw.bestpractice.connection_dqs,
            apsw.bestpractice.connection_recursive_triggers,
            apsw.bestpractice.connection_optimize,
        ):
            hook(connection)

    apsw.connection_hooks.append(conn_hook)

    with with_logging():
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[signal.Signals | SpecialExit] = asyncio.Queue()

        def _stop_loop_on_signal(s: signal.Signals | SpecialExit) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, s)

        signal_service = SignalService()
        sock = signal_service.get_send_socket()

        bot_thread = threading.Thread(target=_wrapped_run_bot, args=(loop, queue, sock))

        signal_service.add_startup(ensure_schema)
        signal_service.add_startup(bot_thread.start)
        signal_service.add_signal_cb(_stop_loop_on_signal)
        signal_service.add_join(bot_thread.join)

        signal_service.run()

    os._exit(0)
