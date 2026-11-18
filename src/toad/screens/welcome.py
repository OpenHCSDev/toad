"""The home view: what the workspace selects while no tab is open.

The view is not a tab: the tab order selects it when its last tab closes and at a launch
that named no session to resume. It draws nothing. While it is selected the comms sidebar
holds the whole window (`SidebarLayout.holds_alone`) with Toad's banner, the project, the
buses and the key hints (`ChannelsSidebar`); opening a row or a new session opens the first
tab, and the sidebar returns to its kept placement beside it. It stays the origin the
sidebar's targets open from.
"""

from __future__ import annotations

from agent_comms.projects.checkouts import Checkout

from toad.app_node import ToadNode
from toad.client.session_scope import HomeSessionOrigin
from toad.navigation_context import HomeNavigation
from toad.navigation_target import FeedTarget, NavigationTarget
from toad.screens.session_view import SessionView
from toad.thread_identity import ThreadIdentity
from toad.widget_actions import TogglesIrc


class WelcomeScreen(
    TogglesIrc,
    HomeNavigation,
    HomeSessionOrigin,
    SessionView,
    ToadNode,
    can_focus=False,
):
    def __init__(self) -> None:
        super().__init__()
        self.project_path = self.app.project_dir

    def read_history_identity(self, project: Checkout) -> ThreadIdentity:
        observed = self.app.coordination_access.observation.observed()
        return ThreadIdentity(
            observed.user_identity(project).incarnation, str(observed.root)
        )

    async def prepare_history_origin(self) -> None:
        app = self.app
        project = self.project_path
        with self.changing_identity():
            self._identity = await app.preparation.run_thread(self.read_history_identity, project)

    async def open_sidebar_target(self, target: NavigationTarget) -> None:
        await self.prepare_history_origin()
        await super().open_sidebar_target(target)

    async def toggle_irc(self) -> None:
        await self.open_sidebar_target(FeedTarget())
