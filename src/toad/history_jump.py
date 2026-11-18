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
from typing import TYPE_CHECKING

from toad.client.history_changes import NO_HISTORY_CHANGE, HistoryChange, NoHistoryChange

if TYPE_CHECKING:
    from toad.view_actions import LatestJumpBar


class JumpsToLatest:
    """A scrolling window that can be put back at its latest entry.

    Carries shared history-window state both backends used to redeclare:

    - ``scroll_revision`` ticks once per scroll motion the window applies; consumers
      compare their stored revision against this window's to learn whether what they
      measured still stands.
    - ``history_change`` tracks whether the scroll underway is a pagination load (a
      change in the history's content). Owned by the shared pager state machine;
      Textual drives it today, Qt inherits the carrier for later wiring.
    - ``can_jump_to_latest`` derives from ``follows_tail``: both backends had the same
      one-liner body. The derivation lives here; subclasses declare ``follows_tail``
      in whatever shape their anchor keeps.
    """

    scroll_revision: int = 0
    history_change: HistoryChange | NoHistoryChange = NO_HISTORY_CHANGE

    @property
    @abstractmethod
    def follows_tail(self) -> bool:
        """Whether this window's reader is at its latest row."""

    @property
    def can_jump_to_latest(self) -> bool:
        """Whether this window is scrolled away from its latest entry."""
        return not self.follows_tail

    @abstractmethod
    def jump_to_latest(self) -> None:
        """Put this window back at its latest entry."""

    jump_bar: LatestJumpBar
    """The toolkit's bar, declared in `view_actions` beside the action it names."""

    def _after_jump_bar_change(self, shown: bool) -> None:
        """Backend-specific follow-up once the bar's visibility has changed; override as needed."""

    def tail_follow_changed(self) -> None:
        """Show the jump bar while the reader is off the tail, hide it once the end is in view.

        Every scroll offset reaches here, so an unchanged state is no change: the footer
        would otherwise re-project bindings per frame. The bar paints the toolkit, and
        `_after_jump_bar_change` is the window's hook for anything downstream (refresh
        bindings, reposition the floating button).
        """
        jump = self.can_jump_to_latest
        if self.jump_bar.jump_shown == jump:
            return
        self.jump_bar.show_jump(jump)
        self._after_jump_bar_change(jump)

    def respond_to_scroll(self, position: float) -> None:
        """Shared post-anchor response to a scroll offset. Both backends' native scroll
        hooks call this after their anchor/follow-tail transition; the `lookahead.observe`
        return gate means a no-travel tick does not restart the settle timer or re-queue
        preparation (previously Qt's `scrolled` restarted settle on every QScroller tick
        even when no travel was recorded, which added per-tick work on top of Android's
        already-slow EGL backing-store flush).
        """
        if self.lookahead.observe(position):
            self._schedule_settle()
        self.request_preparation()
        self.tail_follow_changed()


class ReaderWindow(JumpsToLatest):
    """A history window the reader keys move: a page either way, or back to the latest
    (`reader_actions`). Textual's `HistoryWindow` and Qt's `QtHistoryWindow` both list it."""

    @abstractmethod
    def action_page_down(self) -> None: ...

    @abstractmethod
    def action_page_up(self) -> None: ...


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

    def takes_jump_key(self) -> bool:
        """Whether the jump key is this screen's now, rather than the focused control's."""
        return True
