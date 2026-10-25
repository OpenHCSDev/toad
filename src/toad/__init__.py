from __future__ import annotations

NAME = "toad"
TITLE = "Toad"


def get_version() -> str:
    """Get the current version of Toad.

    Returns:
        str: Version string, e.g "1.2.3"
    """
    from importlib.metadata import version

    return version("batrachian-toad")
