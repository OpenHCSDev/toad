"""Qt's thread-navigation opening placeholder.

Mounted immediately on row-tap so the user sees a loading state while the thread's
metadata resolves off the loop; `prepared.bind(view)` swaps the real content in once
the navigation read completes. Minimal by design — it only has to satisfy
`SessionScope` + `.id` + `.opening_failed` for `session_navigation.new` to mount it
and for `ThreadOpening.run` to drive it.

Decoupling point: Qt's `ThreadOpening.__init__` no longer imports Textual's
`MainScreen`, which cuts the entire Textual-widget pyramid out of the Qt
reachable graph (textual_colours, watchdog, pathspec, ncurses, …).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from toad.client.pending import ThreadOpening
from toad.client.session_scope import SessionScope
from toad.qt.float_layer import QtPendingIndicator
from toad.qt.lines import QtLineRenderer
from toad.qt.metrics import UiGap
from toad.qt.page import Page


class QtOpeningSessionView(Page, SessionScope, QWidget):
    """The Qt placeholder a `ThreadOpening` mounts while async navigation runs.

    `session_navigation.new(identity, lambda: view, ...)` accepts any `SessionScope`
    factory; this view carries just enough state (`.id`, `.opening_failed`) for the
    `ThreadOpening` flow to drive it before `prepared.bind(view)` replaces the content.
    """

    def __init__(self, title: str, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Widget)
        self.id = ""  # workspace_sessions.prepare assigns the real mode name on mount
        self._title = title
        self._error: Exception | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.page, UiGap.page, UiGap.page, UiGap.page)
        # Textual's opening screen shows `ThreadLoading` swept in the theme's colours; Qt
        # shows the same words with Toad's activity sweep, once the shared delay passes so
        # a fast open never flashes it.
        self.pending = QtPendingIndicator(renderer, self)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.hide()
        layout.addStretch(1)
        layout.addWidget(self.pending)
        layout.addWidget(self._label)
        layout.addStretch(1)
        QTimer.singleShot(int(self.pending.pending_delay * 1000), self, self.show_waiting)

    def show_waiting(self) -> None:
        if self._error is None:
            self.pending.show_pending(ThreadOpening)

    @property
    def mode(self) -> str:
        """Qt reads `workspace_sessions.selected.mode` (via `QtToadApp.selected_mode`)
        to identify the currently-shown page; every Qt page must answer `.mode`. On
        `ConversationView` this comes from `self.entry.mode`; on `Welcome` it's the
        `WELCOME` ClassVar. The opening view has no `entry` until `prepared.bind(view)`
        swaps the real view in, so it mirrors its own `.id` which
        `workspace_sessions.prepare` assigns at mount."""
        return self.id

    def opening_failed(self, error: Exception) -> None:
        """Called by `ThreadOpening.run` on a failed navigation; repaint the label
        so the user sees the reason without the row silently doing nothing."""
        self._error = error
        self.pending.clear_pending(ThreadOpening)
        self._label.setText(f"Opening {self._title} failed:\n{error}")
        self._label.show()

    # SessionScope lifecycle methods raise NotImplementedError by default. The opening
    # view holds no Core subscriptions, no presentation and no wire binding — it's a
    # pure placeholder until `prepared.bind(view)` swaps the real view in. Overriding
    # these as no-ops lets `session_navigation.close_views` / `.detach_all` tear the
    # opening view down cleanly without having to guard every call site.

    def close_core_events(self) -> None:
        """Opening view has no Core subscriptions; nothing to close."""

    def belongs_to_wire(self, root) -> bool:
        """Opening view is wire-agnostic until it's replaced by the bound view."""
        return False

    def shown(self, window, visited) -> None:
        """`QtWorkspaceViews.select` calls `page.shown(app, visited)` when a page
        becomes the current widget. Opening view has no visit identity to record;
        `QtWorkspaceViews.swap_page` shows the bound replacement if this placeholder
        was current."""
