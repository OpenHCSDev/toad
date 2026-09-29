from typing import NamedTuple


class MenuItem(NamedTuple):
    """An entry in a Menu."""

    description: str
    action: str | None
    key: str | None = None
