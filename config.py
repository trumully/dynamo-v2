from typing import NamedTuple

from dynaconf import Dynaconf


class HasToken(NamedTuple):
    token: str


settings: HasToken = Dynaconf(
    envvar_prefix="DYNAMO",
    settings_files=[".secrets.toml"],
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
