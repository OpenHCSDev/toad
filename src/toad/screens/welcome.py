"""The home view: what the workspace selects while no tab is open.

The view is not a tab: the tab order selects it when its last tab closes and at a launch
that named no session to resume. It draws nothing. While it is selected the comms sidebar
holds the whole window (`SidebarLayout.holds_alone`) with Toad's banner, the project, the
buses and the key hints (`ChannelsSidebar`); opening a row or a new session opens the first
tab, and the sidebar returns to its kept placement beside it. It stays the origin the
sidebar's targets open from.
"""

from __future__ import annotations

from toad.client.session_scope import HomeSessionOrigin
from toad.navigation_context import HomeNavigation
from toad.navigation_target import FeedTarget
from toad.screens.session_view import SessionView
from toad.thread_identity import SessionIdentity
from toad.widget_actions import TogglesIrc


class WelcomeScreen(
    TogglesIrc,
    HomeNavigation,
    HomeSessionOrigin,
    SessionView,
    can_focus=False,
):
    def __init__(self) -> None:
        super().__init__()
        self.project_path = self.app.project_dir

    def home_identity_read(self, identity: SessionIdentity) -> None:
        with self.changing_identity():
            self._identity = identity

    async def toggle_irc(self) -> None:
        await self.open_sidebar_target(FeedTarget())
