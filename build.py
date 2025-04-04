# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "ruff~=0.11.2",
# ]
# ///

import argparse
import os
from pathlib import Path
from subprocess import Popen  # noqa: S404

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


def main() -> None:
    root = Path(__file__).parent
    os.unsetenv("VIRTUAL_ENV")  # avoids warning when calling uv

    parser = argparse.ArgumentParser(description="Build script")
    parser.add_argument("--check", action="store_true", help="Run checks like linting")
    args = parser.parse_args()

    npx = "npx.cmd" if os.name == "nt" else "npx"

    if args.check:
        run("uv", "run", "ruff", "check")
        run("uv", "run", "ruff", "format", "--diff")
        run("uv", "run", npx, "--yes", "pyright@1.1.398")

    dist = root / "dist"
    run("uv", "build", "--out-dir", dist)


if __name__ == "__main__":
    main()
