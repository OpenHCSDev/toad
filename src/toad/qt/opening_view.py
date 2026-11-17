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

from agent_comms.ui_model.message_category import all_categories
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from toad.client.session_scope import SessionScope
from toad.qt.metrics import UiGap


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
        # Sidebar panels bound while this view is the selected tab (QtCategoryFilter via
        # `thread_pane.bind`) read `view.visible_categories` to decide which message
        # categories to show. Opening view carries all categories as the placeholder
        # default — the real view's own attribute overrides this once `prepared.bind`
        # swaps it in. `ConversationView.__init__` sets the same field at window.py:1061.
        self.visible_categories = all_categories()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.page, UiGap.page, UiGap.page, UiGap.page)
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

    # SessionScope lifecycle methods raise NotImplementedError by default. The opening
    # view holds no Core subscriptions, no presentation and no wire binding — it's a
    # pure placeholder until `prepared.bind(view)` swaps the real view in. Overriding
    # these as no-ops lets `session_navigation.close_views` / `.detach_all` tear the
    # opening view down cleanly without having to guard every call site.

    def close_core_events(self) -> None:
        """Opening view has no Core subscriptions; nothing to close."""

    async def wait_content_ready(self) -> None:
        """The opening view IS the loading state — it's always 'ready' to be shown."""

    async def retire_presentation(self) -> None:
        """No presentation to let go of."""

    def belongs_to_wire(self, root) -> bool:
        """Opening view is wire-agnostic until it's replaced by the bound view."""
        return False

    def reload(self) -> None:
        """`QtToadApp.stores_changed` calls `selected.reload()` on every revision
        tick. Opening view has no content to reload — the bound view's own
        `reload` fires once `prepared.bind` swaps it in."""

    def shown(self, window, visited) -> None:
        """`QtWorkspaceViews.select` calls `page.shown(app, visited)` when a page
        becomes the current widget. Opening view has no visit identity to record;
        the bound view's own `shown` fires once it's mounted."""
