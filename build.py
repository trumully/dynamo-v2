# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///

import argparse
import os
from pathlib import Path
from subprocess import PIPE, Popen  # noqa: S404

_IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"


def run(*command: str | Path) -> None:
    msg = f"Running {' '.join(str(c) for c in command)}"
    if _IS_GITHUB_ACTIONS:
        print(f"::group::{msg}", flush=True)  # noqa: T201
    else:
        print(msg)  # noqa: T201

    process = Popen(command)  # noqa: S603
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
    finally:
        if _IS_GITHUB_ACTIONS:
            print("::endgroup::", flush=True)  # noqa: T201

    if process.returncode != 0:
        msg = f"{command} failed with exit code {process.returncode}"
        raise RuntimeError(msg) from None


def get_output(*command: str | Path) -> str:
    process = Popen(command, stdout=PIPE)  # noqa: S603
    stdout, _ = process.communicate()

    if process.returncode != 0:
        msg = f"{command} failed with exit code {process.returncode}"
        raise RuntimeError(msg) from None

    return stdout.decode("utf-8")


def main() -> None:
    root = Path(__file__).parent
    os.unsetenv("VIRTUAL_ENV")  # avoids warning when calling uv

    parser = argparse.ArgumentParser(description="Build script")
    parser.add_argument("--check", action="store_true", help="Run checks like linting")
    args = parser.parse_args()

    npx = "npx.cmd" if os.name == "nt" else "npx"

    pyproject = root / "pyproject.toml"
    if args.check:
        run("uvx", "ruff", "check")
        run("uvx", "ruff", "format", "--diff")
        run("uv", "run", npx, "--yes", "pyright@1.1.398", "-p", pyproject)

    dist = root / "dist"
    run("uv", "build", "--out-dir", dist)


if __name__ == "__main__":
    main()
