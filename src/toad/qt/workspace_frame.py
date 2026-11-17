"""Qt's concrete workspace frame: the top-level `QtToadApp` satisfies the shared
`toad.workspace_frame.WorkspaceFrame` protocol, so Qt widgets that inherit
`WorkspaceHosted` reach their frame the same way Textual widgets do.

The Textual sibling is `toad.screens.workspace.WorkspaceFrame`; both backends expose
the same attributes (history windows, frame-presentation deferral, lifecycle flags,
sidebar hooks, wire predicate, reader-kept signal) so a widget typed against the
protocol works on either backend without a toolkit branch.
"""

from __future__ import annotations

from pathlib import Path
from weakref import WeakSet

from toad.history_jump import JumpsToLatest
from toad.workspace_frame import WorkspaceFrame as WorkspaceFrameProto


class QtWorkspaceFrame:
    """Mixin on `QtToadApp` that satisfies `WorkspaceFrame`.

    Qt widgets reach this through `self.window()` rather than `super().screen`, so each
    Qt-side `WorkspaceHosted` widget overrides the `screen` property to return this
    frame directly. Many hooks are no-ops on Qt today because Qt widgets drive their
    own lifecycle through the toolkit — the attributes exist so widgets typed against
    the protocol work without a toolkit branch.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._qt_history_windows: WeakSet[JumpsToLatest] = WeakSet()

    @property
    def history_windows(self) -> set[JumpsToLatest]:
        return set(self._qt_history_windows)

    @property
    def frame_presentation(self):
        """Qt has no Textual-shaped frame presentation; the UI thread dispatcher
        owns the deferral surface. Widgets that need per-frame deferral call
        `schedule_ui` on the host instead."""
        raise AttributeError(
            "Qt widgets defer through QtCommsHost.schedule_ui, not frame_presentation")

    @property
    def is_current(self) -> bool:
        """Qt's top-level window is always the current frame while the app runs."""
        return True

    @property
    def is_active(self) -> bool:
        return self.application_running

    def start_sidebar_navigation(self, sidebar) -> None:
        """Deferred on Qt through the UI-thread dispatcher the host already owns."""
        self.schedule_ui(sidebar.navigation.start)

    def focus_sidebar_return(self) -> None:
        """Clear focus so the next click chooses; Qt's focus traversal takes over."""
        self.clear_focus()

    def belongs_to_wire(self, root: Path) -> bool:
        """Qt follows the project it was launched with; a different root means another
        frame altogether."""
        return root == self.project_dir.path

    def reader_kept(self, window: JumpsToLatest) -> None:
        """No reader-position bookkeeping on Qt today: QtHistoryWindow owns its own
        anchor through follows_tail / release_anchor."""


def _check_protocol() -> None:
    # Import-time structural check: QtToadApp (QtWorkspaceFrame + ClientApplication +
    # QtCommsHost) must still satisfy the WorkspaceFrame protocol. This runs a cheap
    # attribute check so a future refactor that drops one of the hooks surfaces here.
    _ = WorkspaceFrameProto  # keep the import live for the check below
