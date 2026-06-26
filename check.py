# /// script
# requires-python = ">=3.14.0"
# dependencies = [
#     "ruff>=0.15.19",
#     "basedpyright~=1.39.8",
# ]
# ///

from __future__ import annotations

import argparse
import os
import subprocess

_IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"


def run(*command: str) -> None:
    group = f"Running {' '.join(str(c) for c in command)}"
    if _IS_GITHUB_ACTIONS:
        print(f"::group::{group}", flush=True)
    else:
        print(group)

    try:
        subprocess.run(command, check=True)
    finally:
        if _IS_GITHUB_ACTIONS:
            print("::endgroup::", flush=True)


def main() -> None:
    os.unsetenv("VIRTUAL_ENV")

    parser = argparse.ArgumentParser(description="Check format, types, linting")
    excl = parser.add_mutually_exclusive_group()
    excl.add_argument("--fix", action="store_true", help="Fix any reported errors where possible", dest="fix")
    args = parser.parse_args()

    if args.fix:
        run("uv", "run", "ruff", "check", "--fix")
        run("uv", "run", "ruff", "format", ".")
    else:
        run("uv", "run", "ruff", "check")
        run("uv", "run", "ruff", "format", "--diff")
        run("uv", "run", "basedpyright", "--warnings")


if __name__ == "__main__":
    main()
