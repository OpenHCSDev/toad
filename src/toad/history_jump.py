"""Putting a scrolled history back at its latest entry, declared where every reader imports it.

The window owns the jump and the screen owns which windows can take one. Both are declared
here rather than on the widgets, because the action that offers the jump, the screen that
holds the windows and the button that names the key all need the contract, and a module
they all import is the repair for the cycle between them.

`@abstractmethod` without `ABC`: a Textual widget's metaclass refuses an `ABC` base
outright, which is why every capability in `widget_actions` is declared this way.
"""

from __future__ import annotations

from abc import abstractmethod

from toad.app_node import ToadNode


class JumpsToLatest(ToadNode):
    """A scrolling window that can be put back at its latest entry."""

    @property
    @abstractmethod
    def can_jump_to_latest(self) -> bool:
        """Whether this window is scrolled away from its latest entry."""

    @abstractmethod
    def jump_to_latest(self) -> None:
        """Put this window back at its latest entry."""


class JumpsHistory(ToadNode):
    """A screen holding history windows, some of which can be put back at their latest entry."""

    @property
    @abstractmethod
    def back_to_bottom_windows(self) -> tuple[JumpsToLatest, ...]:
        """Its drawn history windows that are scrolled away from their latest entry."""
