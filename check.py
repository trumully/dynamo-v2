# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "ruff~=0.11.4",
# ]
# ///

from __future__ import annotations

import os
import sys
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


def run(*command: str | Path) -> None:
    msg = f"Running {' '.join(str(c) for c in command)}"
    with github_action(msg):
        process = Popen(command)
        try:
            process.wait()
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
        finally:
            if process.returncode != 0:
                sys.exit(process.returncode)


def main() -> None:
    os.unsetenv("VIRTUAL_ENV")  # Prevents warnings when running uv

    if _IS_GITHUB_ACTIONS:
        os.environ["RUFF_OUTPUT_FORMAT"] = "github"

    run("uv", "run", "ruff", "check")
    run("uv", "run", "ruff", "format", "--diff")
    run("uv", "run", "npx", "--yes", "pyright@1.1.400")


if __name__ == "__main__":
    main()
