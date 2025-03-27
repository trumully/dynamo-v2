from __future__ import annotations

import os


def main() -> None:
    os.umask(0o077)

    from .runner import run_bot

    run_bot()
