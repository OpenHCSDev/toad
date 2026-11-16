"""The client application every native frontend composes: Core events, the launch's agent
binding and lifetime, session and thread navigation, thread actions, the sidebar's state,
the tab order and its tracker, and the coordination access over the launch's connection.

A native application inherits this beside its toolkit's application class, calls
initialize_client once from its own constructor, and answers show_history_step with its
own view switch.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Awaitable

from agent_comms.nominal.field_codec import AcpSessionId, NoAcpSessionId

from toad.application_lifetime import ApplicationLifetime
from toad.client.connection import CoreConnection
from toad.client.db import DB
from toad.client.session_tracker import OpenTab, SessionTracker, SidebarState
from toad.client.tab_order import TabOrder
from toad.constants import WELCOME
from toad.core import events as core_events
from toad.core import session_requests
from toad.launch_binding import AgentBinding
from toad.navigation_preparation import NavigationReader
from toad.session_host import NavigationHost
from toad.session_navigation import SessionNavigation
from toad.thread_actions import ThreadActions
from toad.thread_navigation import ThreadNavigator


class ClientApplication(NavigationHost):
    """One launch's client state and its session operations, shared by every frontend."""

    def initialize_client(
        self,
        agent_binding: AgentBinding,
        connection: CoreConnection,
        agent_session_id: AcpSessionId | NoAcpSessionId = NoAcpSessionId(),
    ) -> None:
        """The launch's client owners, built once from the native constructor."""
        self.events = core_events.CoreEventStream(self)
        self.navigation_reader = NavigationReader()
        self.agent_binding = agent_binding
        self.application = ApplicationLifetime(self, agent_session_id)
        self.session_navigation = SessionNavigation(self)
        self.thread_navigation = ThreadNavigator(self)
        self.thread_actions = ThreadActions(self)
        self.sidebar_state = SidebarState()
        self.tab_order = TabOrder(
            lambda identity: self.show_history_step(identity.mode_name),
            home=WELCOME,
            db=DB(),
            scopes=connection.tab_scopes(),
        )
        self._session_tracker = SessionTracker(self.tab_order)
        self.coordination_access = connection.open_access(self)

    @abstractmethod
    def show_history_step(self, mode: str) -> Awaitable[object]:
        """Show the tab a history step selected, in the native view."""

    async def get_db(self) -> DB:
        """Get an instance of the database."""
        db = DB()
        return db

    @property
    def session_tracker(self) -> SessionTracker:
        return self._session_tracker

    def has_session(self, mode: str) -> bool:
        return self.session_navigation.session_details(mode) is not None

    def close_session(self, mode: str) -> None:
        self.session_navigation.events.publish(session_requests.SessionClose(mode))

    def open_direct_messages(self, target: str) -> None:
        self.session_navigation.direct_messages(target)

    @property
    def open_tabs(self) -> tuple[OpenTab, ...]:
        return self.session_navigation.tabs
