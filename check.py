# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "ruff~=0.11.4",
# ]
# ///

import os
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

    if process.returncode != 0:
        msg = f"{command} failed with exit code {process.returncode}"
        raise RuntimeError(msg) from None


def main() -> None:
    os.unsetenv("VIRTUAL_ENV")  # Prevents warnings when running uv
    npx = "npx.cmd" if os.name == "nt" else "npx"

    if _IS_GITHUB_ACTIONS:
        os.environ["RUFF_OUTPUT_FORMAT"] = "github"

    run("uv", "run", "ruff", "check")
    run("uv", "run", "ruff", "format", "--diff")
    run("uv", "run", npx, "--yes", "pyright@1.1.398")


if __name__ == "__main__":
    main()
