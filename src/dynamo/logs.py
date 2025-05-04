from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from queue import SimpleQueue

import apsw.ext

from . import _typing_shim as t
from .utils import dirs, resolve_path_with_links

_T_contra = t.TypeVar("_T_contra", contravariant=True)


if t.TYPE_CHECKING:
    from types import TracebackType

    BaseLogger: type[logging.Logger] = logging.Logger
    type _SysExcInfoType = (
        tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]
    )
    type _ExcInfoType = bool | _SysExcInfoType | BaseException | None

    class LoggerKwarg(t.TypedDict, total=False):
        exc_info: _ExcInfoType
        stack_info: bool
        stacklevel: int
        extra: Mapping[str, object] | None

else:
    BaseLogger: type[logging.Logger] = logging.getLoggerClass()

TRACE_LEVEL = 5


class Logger(BaseLogger):
    def trace(self, msg: str, *args: object, **kwargs: t.Unpack[LoggerKwarg]) -> None:
        if self.isEnabledFor(TRACE_LEVEL):
            self.log(TRACE_LEVEL, msg, *args, **kwargs)


def get_logger(name: str | None = None, /) -> Logger:
    return t.cast("Logger", logging.getLogger(name))


logging.setLoggerClass(Logger)
logging.addLevelName(TRACE_LEVEL, "TRACE")


class SupportsWrite(t.Protocol[_T_contra]):
    def write(self, s: _T_contra, /) -> object: ...


class SupportsWriteAndIsTTY(t.Protocol[_T_contra]):
    def write(self, s: _T_contra, /) -> object: ...
    def isatty(self) -> bool: ...


type Stream[T] = SupportsWrite[T] | SupportsWriteAndIsTTY[T]


class KnownWarningFilter(logging.Filter):
    known_messages: tuple[str, ...] = (
        "Guilds intent seems to be disabled. This may cause state related issues.",
        "PyNaCl is not installed, voice will NOT be supported",
    )

    @t.override
    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        return record.msg not in self.known_messages


dt_fmt = "%Y-%m-%d %H:%M:%S"
FMT = logging.Formatter("[%(asctime)s] [%(levelname)-8s}] %(name)s: %(message)s", dt_fmt)


_MSG_PREFIX = "\x1b[30;1m%(asctime)s\x1b[0m "
_MSG_POSTFIX = "%(levelname)-8s\x1b[0m \x1b[35m%(name)s\x1b[0m %(message)s"


LC = (
    (logging.DEBUG, "\x1b[40;1m"),
    (logging.INFO, "\x1b[34;1m"),
    (logging.WARNING, "\x1b[33;1m"),
    (logging.ERROR, "\x1b[31m"),
    (logging.CRITICAL, "\x1b[41m"),
)

FORMATS = {
    level: logging.Formatter(_MSG_PREFIX + color + _MSG_POSTFIX, "%Y-%m-%d %H:%M:%S")
    for level, color in LC
}


class AnsiTermFormatter(logging.Formatter):
    @t.override
    def format(self, record: logging.LogRecord) -> str:
        formatter = FORMATS.get(record.levelno)
        if formatter is None:
            formatter = FORMATS[logging.DEBUG]
        if record.exc_info is not None:
            text = formatter.formatException(record.exc_info)
            record.exc_text = f"\x1b[31m{text}\x1b[0m"
        output = formatter.format(record)
        record.exc_text = None
        return output


def use_color_formatting(stream: Stream[str], /) -> bool:
    is_a_tty = False

    if hasattr(stream, "isatty"):
        is_a_tty = t.cast("SupportsWriteAndIsTTY[str]", stream).isatty()

    if os.environ.get("TERM_PROGRAM") == "vscode":
        return is_a_tty

    if sys.platform == "win32" and "WT_SESSION" not in os.environ:
        return False

    return is_a_tty


@contextmanager
def with_logging() -> Generator[None]:
    q: SimpleQueue[t.Any] = SimpleQueue()
    q_handler = logging.handlers.QueueHandler(q)
    q_handler.addFilter(KnownWarningFilter())
    stream_h = logging.StreamHandler()

    log_path = resolve_path_with_links(dirs.user_log_path, folder=True)
    log_loc = log_path / "dynamo.log"
    rotating_file_handler = logging.handlers.RotatingFileHandler(
        log_loc, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )

    stream_fmt = AnsiTermFormatter() if use_color_formatting(sys.stderr) else FMT
    stream_h.setFormatter(stream_fmt)

    rotating_file_handler.setFormatter(FMT)

    q_listener = logging.handlers.QueueListener(q, stream_h, rotating_file_handler)
    root_logger = get_logger()
    root_logger.setLevel(TRACE_LEVEL)
    root_logger.addHandler(q_handler)

    get_logger("discord").setLevel(logging.WARNING)
    get_logger("discord.client").setLevel(logging.INFO)
    get_logger("asyncio").setLevel(logging.INFO)
    get_logger("PIL.PngImagePlugin").setLevel(logging.WARNING)

    apsw_log = get_logger("apsw_forwarded")
    apsw.ext.log_sqlite(logger=apsw_log)

    try:
        q_listener.start()
        yield
    finally:
        q_listener.stop()
