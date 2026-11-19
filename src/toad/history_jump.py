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

from toad.client.history_changes import NO_HISTORY_CHANGE, HistoryChange, NoHistoryChange

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

    def tail_follow_changed(self) -> None:
        """A tail transition has no extra display unless the window declares one."""

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


class FollowsTail(JumpsToLatest):
    """The one place a history window's reader joins or leaves its tail.

    Joining or leaving is one change of the reader's follow intent: it counts as a reader
    move (`scroll_revision`, unless the window is moving itself), the window applies it in its
    toolkit (`apply_anchor`), and the window's declared follow-up sees the result. Each window
    lists this before its toolkit's scroll base, so this `anchor` answers in both frontends
    ahead of Textual's own `Widget.anchor`, and a window supplies only `apply_anchor`.

    A subclass that defines `anchor` again is refused when its class is created: Qt's window
    once carried its own copy without the last step, so its back-to-bottom bar stayed up
    after a jump until the reader scrolled again (Tristan, Android, 2026-11-18)."""

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "anchor" in vars(cls):
            raise TypeError(f"{cls.__qualname__} redefines FollowsTail.anchor; "
                            "a window supplies apply_anchor, its toolkit's own move, instead")

    def anchor(self, anchor: bool = True) -> None:
        changed = self.follows_tail != anchor
        if not self._restoring and changed:
            self.scroll_revision += 1
        self.apply_anchor(anchor)
        if changed:
            self.tail_follow_changed()

    @abstractmethod
    def apply_anchor(self, anchor: bool) -> None:
        """Join (`anchor`) or leave the tail in this toolkit, without counting or showing it."""


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
