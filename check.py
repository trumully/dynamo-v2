# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "ruff~=0.11.8",
#     "basedpyright~=1.29.1",
# ]
# ///

from __future__ import annotations

import argparse
import os
from collections.abc import Generator
from contextlib import contextmanager
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


def run(*command: str) -> None:
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
                msg = f"Failed with code {process.returncode}"
                raise RuntimeError(msg)


def main() -> None:
    os.umask(0o077)

    os.unsetenv("VIRTUAL_ENV")  # Prevents warnings when running uv

    if _IS_GITHUB_ACTIONS:
        os.environ["RUFF_OUTPUT_FORMAT"] = "github"

    parser = argparse.ArgumentParser(description="Check format, types, linting")
    excl = parser.add_mutually_exclusive_group()
    excl.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="fix any reported errors where possible",
        dest="fix",
    )
    args = parser.parse_args()

    run("uv", "run", "ruff", "check", "--fix" if args.fix else "")
    run("uv", "run", "ruff", "format", "--diff" if not args.fix else "src/dynamo/")
    run("uv", "run", "basedpyright", "--warnings")


if __name__ == "__main__":
    main()
