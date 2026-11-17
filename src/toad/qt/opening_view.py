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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from toad.client.session_scope import SessionScope


class QtOpeningSessionView(SessionScope, QWidget):
    """The Qt placeholder a `ThreadOpening` mounts while async navigation runs.

    `session_navigation.new(identity, lambda: view, ...)` accepts any `SessionScope`
    factory; this view carries just enough state (`.id`, `.opening_failed`) for the
    `ThreadOpening` flow to drive it before `prepared.bind(view)` replaces the content.
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Widget)
        self.id = ""  # workspace_sessions.prepare assigns the real mode name on mount
        self._title = title
        self._error: Exception | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        self._label = QLabel(f"Opening {title}…", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(self._label)
        layout.addStretch(1)

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
        self._label.setText(f"Opening {self._title} failed:\n{error}")
