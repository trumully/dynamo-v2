from __future__ import annotations

import os

from dynamo.runner import run_bot


def main() -> None:
    os.umask(0o077)

    run_bot()


if __name__ == "__main__":
    main()
