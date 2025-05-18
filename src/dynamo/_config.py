# Explicitly omitting from __future__ import annotations

import os
import re

from dynaconf.typed import Dynaconf, Options, Validator  # pyright: ignore[reportMissingTypeStubs]

from . import _typing as t

# A discord bot token is a string that matches the following pattern:
# >>> "[M|N|O]XXXXXXXXXXXXXXXXXXXXXXX[XX].XXXXXX.XXXXXXXXXXXXXXXXXXXXXXXXXXX"
# https://discord.com/developers/docs/reference#authentication
bot_regex = r"[MNO][a-zA-Z\d_-]{23,25}\.[a-zA-Z\d_-]{6}\.[a-zA-Z\d_-]{27}"

snowflake_regex = r"[0-9]{15,20}"


def is_snowflake(value: int) -> bool:
    return value == 0 or (bool(re.match(snowflake_regex, str(value))) and value.bit_length() >= 43)


# https://github.com/dynaconf/dynaconf/pull/1107
class Config(Dynaconf):
    dynaconf_options: Options = Options(envvar_prefix="DYNAMO", settings_files=[".secrets.toml"])
    token: t.Annotated[str, Validator(regex=bot_regex)] = ""
    dev_guild: t.Annotated[int, Validator(condition=is_snowflake)] = 0


config: Config = Config()


def get_token() -> str:
    return os.getenv("DYNAMO_TOKEN") or config.token


__all__ = ("config", "get_token")
