from __future__ import annotations

import os
from pathlib import Path

import platformdirs

platformdir = platformdirs.PlatformDirs("dynamo", "trumully", roaming=False)


def resolve_path_with_links(path: Path, folder: bool = False) -> Path:
    try:
        return path.resolve(strict=True)
    except FileNotFoundError:
        path = resolve_path_with_links(path.parent, folder=True) / path.name
        if folder:
            # python default = read/write/traversable (0o777)
            path.mkdir(mode=0o700)
        else:
            # python default = read/writable (0o666)
            path.mkdir(mode=0o600)
        return path.resolve(strict=True)


ROOT = resolve_path_with_links(Path(__file__).parent.parent.parent)


def get_token() -> str:
    from config import settings

    return os.getenv("DYNAMO_TOKEN") or settings.token
