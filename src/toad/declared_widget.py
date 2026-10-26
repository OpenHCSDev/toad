"""Declaration-owned widget membership without replacing the native metaclass."""
from __future__ import annotations

from abc import update_abstractmethods
from inspect import isabstract
from typing import ClassVar, Self, cast


class DeclaredWidget:
    """Cooperative widget families register their concrete declarations once."""

    __abstractmethods__: ClassVar[frozenset[str]] = frozenset()
    _members: ClassVar[list[type[DeclaredWidget]]] = []

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # The type descriptor is class-local; initialize it before ABC derives it.
        cls.__abstractmethods__ = frozenset()
        update_abstractmethods(cls)
        if not isabstract(cls):
            DeclaredWidget._members.append(cls)

    @classmethod
    def members_with(cls, capability: type) -> tuple[type[Self], ...]:
        return tuple(
            cast(type[Self], member) for member in DeclaredWidget._members
            if issubclass(member, cls) and issubclass(member, capability)
        )
