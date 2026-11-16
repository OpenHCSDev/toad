"""The client application every native frontend composes: Core events, the launch's agent
binding and lifetime, session and thread navigation, thread actions, the sidebar's state,
the tab order and its tracker, and the coordination access over the launch's connection.

A native application inherits this beside its toolkit's application class, calls
initialize_client once from its own constructor, and answers show_history_step with its
own view switch. Changing bus switches the connection under these owners; none of them is
built again (switch_bus).
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Awaitable
from functools import partial

from agent_comms.nominal.field_codec import AcpSessionId, NoAcpSessionId
from formbridge.operations import OperationKind

from toad.application_lifetime import ApplicationLifetime, ApplicationStart
from toad.client.bus_selection import BusChoice, BusPickerHost
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


class BusSwitch(OperationKind):
    """Switches the application onto a bus the reader chose."""


class ClientApplication(BusPickerHost, NavigationHost):
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
            scopes=lambda: self.coordination_access.connection.tab_scopes(),
        )
        self._session_tracker = SessionTracker(self.tab_order)
        self.coordination_access = connection.open_access(self)
        # One switch at a time: a second pick waits for the first to finish moving the owners.
        self.bus_switching = asyncio.Lock()

    def open_bus(self, choice: BusChoice) -> None:
        """Switch this session onto a bus the reader picked."""
        self.run_operation(BusSwitch, partial(self.switch_bus, choice))

    async def switch_bus(self, choice: BusChoice) -> None:
        """Swap the connection, not the app.

        The open tabs' views belong to the bus being left: they close, and its saved roster
        stays under its location for the next visit. The one coordination access then
        observes the chosen Core, which rebinds every view subscribed to it, and the tabs
        saved under the new Core's location open as this frontend's start opens them; a
        start still opening the launch's tabs finishes first.
        """
        await self.wait_operations(ApplicationStart)
        async with self.bus_switching:
            connection = await self.preparation.run_thread(self.connection_for, choice)
            await self.session_navigation.leave_bus()
            await self.coordination_access.switch_connection(connection)
            await self.open_saved_tabs()

    @abstractmethod
    def connection_for(self, choice: BusChoice) -> CoreConnection:
        """The connection ``choice`` names, read by the parser this frontend launches with."""

    async def open_saved_tabs(self) -> None:
        """Open the tabs the observed Core saved, as this frontend's start opens them."""
        await self.application.open_saved_tabs()

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
