"""Declaration-owned widget membership without replacing the native metaclass."""
from __future__ import annotations

from inspect import isabstract
from typing import ClassVar, Self


class DeclaredWidget:
    """Cooperative widget families register their declarations once; the message-pump
    metaclass decides which are abstract, after __init_subclass__ has run, so membership
    asks at read time."""

    _members: ClassVar[list[type[DeclaredWidget]]] = []

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        DeclaredWidget._members.append(cls)

    @classmethod
    def members(cls) -> tuple[type[Self], ...]:
        return tuple(
            member for member in DeclaredWidget._members
            if issubclass(member, cls) and not isabstract(member)
        )
