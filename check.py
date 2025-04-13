# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "ruff~=0.11.4",
# ]
# ///

import os
import signal
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from subprocess import Popen

_IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"


@contextmanager
def github_action(name: str) -> Generator[None]:
    try:
        if _IS_GITHUB_ACTIONS:
            print(f"::group::{name}", flush=True)
        else:
            print(name)
        yield
    finally:
        if _IS_GITHUB_ACTIONS:
            print("::endgroup::", flush=True)


@contextmanager
def defer_signal(signum: int) -> Generator[None]:
    original_handler = None
    defer_handle_args: tuple[object, ...] | None = None

    def defer_handle(*args: object) -> None:
        nonlocal defer_handle_args
        defer_handle_args = args

    original_handler = signal.getsignal(signum)
    if (
        original_handler is None
        or not callable(original_handler)
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    try:
        signal.signal(signum, defer_handle)
        yield
    finally:
        signal.signal(signum, original_handler)
        if defer_handle_args is not None:
            original_handler(*defer_handle_args)


@contextmanager
def PopenDeferringSIGINTDuringConstruction(
    *command: str | Path,
) -> Generator[Popen[bytes]]:
    with defer_signal(signal.SIGINT):
        p = Popen(command)

    with p:
        yield p


def run(*command: str | Path, group: str | None = None) -> None:
    if group is None:
        group = f"Running {' '.join(str(c) for c in command)}"
    with github_action(group), PopenDeferringSIGINTDuringConstruction(*command) as p:
        try:
            p.wait()
        except KeyboardInterrupt:
            p.terminate()
            p.wait()
        finally:
            if p.returncode not in {0, 255}:
                msg = f"{command} failed with exit code {p.returncode}"
                if _IS_GITHUB_ACTIONS:
                    print(f"::error::{msg}", flush=True)
                else:
                    print(f"\x1b[31m{msg}\x1b[0m")
                sys.exit(p.returncode)


def main() -> None:
    os.unsetenv("VIRTUAL_ENV")  # Prevents warnings when running uv
    npx = "npx.cmd" if os.name == "nt" else "npx"

    if _IS_GITHUB_ACTIONS:
        os.environ["RUFF_OUTPUT_FORMAT"] = "github"

    run("uv", "run", "ruff", "check")
    run("uv", "run", "ruff", "format", "--diff")
    run("uv", "run", npx, "--yes", "pyright@1.1.399")


if __name__ == "__main__":
    main()
