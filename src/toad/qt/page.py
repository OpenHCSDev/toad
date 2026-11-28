"""The Qt `Page` base: a page of the window shown when selected, read again when
Core's stores change.

Lives in its own module (rather than `toad.qt.window`) because `QtThreadView`
inherits it, and `toad.qt.acp_tab` inherits `QtThreadView`. If `Page` lived in
window.py, then `thread_view → window → acp_tab (via window.py's tail import) →
thread_view` would cycle — the partial module would raise on the inner
`from toad.qt.thread_view import QtThreadView`. Splitting `Page` out breaks the
chain so both views can inherit it without the cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from toad.client.tab_identity.kinds import CommsTab
from toad.navigation_context import NavigationOwner, NoNavigationOwner

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp


class Page:
    """A page of the window: shown when selected, read again when Core's stores change."""

    id: str

    @property
    def mode(self) -> str:
        return self.id

    def reload(self) -> None:
        """A page fed by its own subscription has nothing to read again."""

    def workspace_navigation_owner(self, views) -> NavigationOwner:
        """What the workspace navigates through while this page is selected
        (`QtWorkspaceViews.navigation_owner`): nothing, for a page that does not navigate."""
        return NoNavigationOwner(views.app)

    def external_transcript_changed(self) -> None:
        """A page showing no thread's transcript has no CLI items to read."""

    def viewport_geometry_changed(self) -> None:
        """The enclosing window resized or its safe-area margins changed; pages without a
        composer have nothing to refit."""

    def shown(self, window: QtToadApp, visited: Callable[[CommsTab], object]) -> None:
        """Selected: read again; a tab passes its identity to the visit history."""
        self.reload()
