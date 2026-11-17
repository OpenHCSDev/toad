"""Qt's thread-navigation opening placeholder.

Mounted immediately on row-tap so the user sees a loading state while the thread's
metadata resolves off the loop; `prepared.bind(view)` fills in the real content once
the navigation read completes.

Decoupling point: Qt's `ThreadOpening.__init__` no longer imports Textual's
`MainScreen`, which cuts the entire Textual-widget pyramid out of the Qt
reachable graph (textual_colours, watchdog, pathspec, ncurses, ...). See
`toad.qt.window.QtToadApp.make_opening_view` and `toad.session_host.NavigationHost`.

Scope note: the complete structural fix (one class for opening + bound lifecycle,
mirroring Textual's `MainScreen.opening(...)` → `prepared.bind(view)` on the SAME
widget) requires making `QtAcpSessionView.__init__` tolerate `session_pk=None`,
deferred transcript/history/composer setup and a stub presentation. That's a
multi-PR refactor of `QtAcpSessionView`. This file keeps the placeholder as a
separate class and overrides every page / lifecycle hook so the "two states can
disagree" surface is bounded — any call `ThreadOpening` or the Qt page lifecycle
makes on the mounted opening view resolves to a no-op here, and the real view
takes over once `prepared.bind(view)` lands.
"""

from __future__ import annotations

from agent_comms.ui_model.message_category import all_categories
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from toad.client.session_scope import SessionScope


class _OpeningPresentation:
    """Placeholder for `view.presentation.sources` writes by `ThreadNavigation.bind`.
    A real view supplies a `TranscriptPresentation` whose `.sources` carries the
    mailbox load plan; the opening view has no transcript yet, so bind-writes land
    on this throwaway and the swapped-in real view supplies the real presentation."""

    class _Sources:
        def __init__(self) -> None:
            self.load_plan = None

    def __init__(self) -> None:
        self.sources = _OpeningPresentation._Sources()


class QtOpeningSessionView(SessionScope, QWidget):
    """The Qt placeholder a `ThreadOpening` mounts while async navigation runs.

    `session_navigation.new(identity, lambda: view, ...)` accepts any `SessionScope`
    factory; this view carries just enough state and lifecycle hooks (as no-ops)
    for the `ThreadOpening` flow, the `QtWorkspaceViews` page selection and the
    `ThreadNavigation.bind` family to drive it before the real view replaces it.
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Widget)
        self.id = ""  # workspace_sessions.prepare assigns the real mode name on mount
        self._title = title
        self._error: Exception | None = None
        # Placeholder presentation so `ThreadNavigation.bind(screen)` writes to
        # `screen.presentation.sources.load_plan = plan` land somewhere valid.
        # The real view, once mounted, supplies the real TranscriptPresentation.
        self.presentation = _OpeningPresentation()
        # `QtCategoryFilter.present` reads `view.visible_categories`; opening view
        # shows the full set as its placeholder default. Mirrors
        # `ConversationView.__init__` at `src/toad/qt/window.py:1061`.
        self.visible_categories = all_categories()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        self._label = QLabel(f"Opening {title}…", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(self._label)
        layout.addStretch(1)

    # ---- Qt page identity ----

    @property
    def mode(self) -> str:
        """Qt reads `workspace_sessions.selected.mode` (via `QtToadApp.selected_mode`)
        to identify the currently-shown page. `ConversationView.mode` reads
        `self.entry.mode`; `Welcome.mode` is the `WELCOME` ClassVar. The opening
        view has no `entry` until the real view replaces it, so it mirrors its
        own `.id`, which `workspace_sessions.prepare` assigns at mount."""
        return self.id

    # ---- Qt page lifecycle (shown/reload) ----

    def shown(self, window, visited) -> None:
        """`QtWorkspaceViews.select` calls `page.shown(app, visited)` when a page
        becomes the current widget. Opening view has no visit identity to record;
        the real view's `shown` fires once mounted."""

    def reload(self) -> None:
        """`QtToadApp.stores_changed` calls `selected.reload()` on every revision
        tick. Opening view has no content to reload."""

    # ---- ThreadNavigation.bind hooks ----

    def use_mailbox(self) -> None:
        """`ThreadNavigation.bind(screen)` calls `screen.use_mailbox()` on Textual's
        `MainScreen` to switch the screen's content to mailbox presentation. The
        opening view has no mailbox content yet; the real view that replaces it
        does mailbox-presentation setup in its own init."""

    # ---- SessionScope lifecycle no-ops (opening view has no subscriptions /
    #      presentation / wire binding — it's a pure placeholder until the real
    #      view takes over). These OVERRIDES stay on the placeholder, not on
    #      SessionScope itself, because a REAL session view that forgets to
    #      close its subscriptions SHOULD loud-fail at teardown. ----

    def close_core_events(self) -> None:
        """Opening view has no Core subscriptions; nothing to close."""

    async def wait_content_ready(self) -> None:
        """The opening view IS the loading state — it's always 'ready' to be shown."""

    async def retire_presentation(self) -> None:
        """No presentation to let go of."""

    def belongs_to_wire(self, root) -> bool:
        """Opening view is wire-agnostic until the real view replaces it."""
        return False

    def opening_failed(self, error: Exception) -> None:
        """Called by `ThreadOpening.run` on a failed navigation; repaint the label
        so the user sees the reason without the row silently doing nothing."""
        self._error = error
        self._label.setText(f"Opening {self._title} failed:\n{error}")
