from __future__ import annotations

import argparse
import getpass
import os

from .runner import run_bot
from .utils import store_token


def run_setup() -> None:
    prompt = (
        "Paste Discord token you would like to use for the bot here "
        "(won't be visible) then press Enter. "
        "This will be stored for later use >"
    )
    token = getpass.getpass(prompt)
    if not token:
        msg = "Not storing empty token"
        raise RuntimeError(msg)
    store_token(token)


def main() -> None:
    os.umask(0o077)

    parser = argparse.ArgumentParser(description="Dynamo")
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument("--setup", action="store_true", default=False, help="Run interactive setup", dest="isetup")
    mutex.add_argument("--set-token-to", default=None, help="Provide a token directly to be stored for use", dest="token")
    args = parser.parse_args()

    if args.isetup:
        run_setup()
    elif args.token:
        store_token(args.token)
    else:
        run_bot()


if __name__ == "__main__":
    main()
