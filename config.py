from dynaconf.typed import Dynaconf, Options, Validator  # type: ignore[reportMissingTypeStubs]
from dynamo import _typings as t

# A discord bot token is a string that matches the following pattern:
# >>> "[M|N|O]XXXXXXXXXXXXXXXXXXXXXXX[XX].XXXXXX.XXXXXXXXXXXXXXXXXXXXXXXXXXX"
# https://discord.com/developers/docs/reference#authentication
bot_regex = r"[MNO][a-zA-Z\d_-]{23,25}\.[a-zA-Z\d_-]{6}\.[a-zA-Z\d_-]{27}"


class Settings(Dynaconf):
    dynaconf_options = Options(
        envvar_prefix="DYNAMO",
        settings_files=[".secrets.toml"],
    )
    token: t.Annotated[str, Validator(regex=bot_regex)]  # type: ignore[reportUninitializedInstanceVariable]


settings = Settings()
