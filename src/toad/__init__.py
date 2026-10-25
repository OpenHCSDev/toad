from __future__ import annotations

import platform as _platform

from toad.platform import OS, Platform  # noqa: F401 -- OS is the catalog key type

NAME = "toad"
TITLE = "Toad"

host: type[Platform] = Platform.decode(_platform.system())


def get_version() -> str:
    """Get the current version of Toad.

    Returns:
        str: Version string, e.g "1.2.3"
    """
    from importlib.metadata import version

    return version("batrachian-toad")
