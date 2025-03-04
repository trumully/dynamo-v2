from __future__ import annotations

import os

if __name__ == "__main__":
    os.umask(0o077)

    from .runner import run_bot

    run_bot()
