"""Putting a scrolled history back at its latest entry, declared where every reader imports it.

The window owns the jump and the screen owns which windows can take one. Both are declared
here rather than on the widgets, because the action that offers the jump, the screen that
holds the windows and the button that names the key all need the contract, and a module
they all import is the repair for the cycle between them.

Plain mixins, no `ABC` and no toolkit base: a Textual widget's metaclass refuses an `ABC`
base outright (which is why every capability in `widget_actions` is declared this way), and
a Qt widget that inherits one of these must not drag Textual's DOMNode in through its MRO.
Both backends' concrete windows list one of these beside their own toolkit widget.
"""

from __future__ import annotations

from abc import abstractmethod


class JumpsToLatest:
    """A scrolling window that can be put back at its latest entry."""

    @property
    @abstractmethod
    def can_jump_to_latest(self) -> bool:
        """Whether this window is scrolled away from its latest entry."""

    @abstractmethod
    def jump_to_latest(self) -> None:
        """Put this window back at its latest entry."""


class JumpsHistory:
    """A screen holding history windows, some of which can be put back at their latest entry.

    The window registry is the one shared fact: anchors register themselves on the
    screen (`self.screen.history_windows.add(self)`) for their lifetime, and both
    backends read the same set to drive jump actions and layout bookkeeping. Keep it
    here so a Qt `screen` and a Textual `screen` behave the same for consumers.
    """

    @property
    def history_windows(self) -> set[JumpsToLatest]:
        """The mounted history windows this screen holds. Lazy-init so subclasses
        don't need to touch `__init__`; mutable (anchors `.add` / `.discard` it)."""
        existing = self.__dict__.get("_history_windows")
        if existing is None:
            existing = set()
            self.__dict__["_history_windows"] = existing
        return existing

    @property
    @abstractmethod
    def back_to_bottom_windows(self) -> tuple[JumpsToLatest, ...]:
        """Its drawn history windows that are scrolled away from their latest entry."""
