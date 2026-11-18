"""How a window opened over the app is laid out, for each screen width class: one family both
frontends' presentations inherit, so neither can lay a window out by a rule of its own.

On a NARROW screen (a phone) a window fills the app, as a phone app's page does (`FillsApp`).
On a WIDE one it sits beside the app's content (`BesideApp`): Textual draws a side panel half
the screen wide, Qt a dialog floating over the app. Each frontend's members inherit one of these
and its own toolkit base, and each frontend finds its member for a width through `for_width` on
its toolkit base, so a width class with no member in a frontend fails there, not silently.
"""

from __future__ import annotations

from abc import ABC
from typing import ClassVar

from toad.screen_width import ScreenWidth


class WindowPresentation(ABC):
    """How a window over the app is laid out on a screen of one width class."""

    width: ClassVar[ScreenWidth]

    @classmethod
    def for_width(cls, width: ScreenWidth) -> type[WindowPresentation]:
        """The member of this (toolkit's) family that lays a window out at `width`."""
        pending, found = list(cls.__subclasses__()), []
        while pending:
            member = pending.pop()
            pending.extend(member.__subclasses__())
            if "width" in {name for ancestor in member.__mro__ for name in vars(ancestor)} \
                    and member.width is width and member not in found:
                found.append(member)
        concrete = [member for member in found if not member.__abstractmethods__]
        if len(concrete) != 1:
            raise TypeError(f"{cls.__qualname__} has {len(concrete)} presentations for {width.name}: "
                            f"{[member.__qualname__ for member in concrete]}")
        return concrete[0]


class FillsApp(WindowPresentation):
    """A narrow screen's window: it takes the app's whole window, as a phone app's page does."""

    width = ScreenWidth.NARROW


class BesideApp(WindowPresentation):
    """A wide screen's window: it leaves the app's content in view beside or under it."""

    width = ScreenWidth.WIDE
