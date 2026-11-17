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

    @abstractmethod
    def _jump_bar_shown(self) -> bool:
        """Whether the backend's jump bar is currently visible."""

    @abstractmethod
    def _set_jump_bar_shown(self, shown: bool) -> None:
        """Show or hide the backend's jump bar."""

    def _after_jump_bar_change(self, shown: bool) -> None:
        """Backend-specific follow-up once the bar's visibility has changed; override as needed."""

    def tail_follow_changed(self) -> None:
        """Show the jump bar while the reader is off the tail, hide it once the end is in view.

        Every scroll offset reaches here, so an unchanged state is no change: the footer
        would otherwise re-project bindings per frame. The subclass's `_jump_bar_shown` and
        `_set_jump_bar_shown` paint the toolkit, and `_after_jump_bar_change` is its hook
        for anything downstream (refresh bindings, reposition the floating button).
        """
        jump = self.can_jump_to_latest
        if self._jump_bar_shown() == jump:
            return
        self._set_jump_bar_shown(jump)
        self._after_jump_bar_change(jump)


class JumpsHistory:
    """A screen holding history windows, some of which can be put back at their latest entry."""

    @property
    @abstractmethod
    def back_to_bottom_windows(self) -> tuple[JumpsToLatest, ...]:
        """Its drawn history windows that are scrolled away from their latest entry."""
