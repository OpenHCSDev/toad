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
import time
from abc import abstractmethod
from collections.abc import Awaitable
from functools import partial

from agent_comms.nominal.field_codec import AcpSessionId, NoAcpSessionId
from agent_comms.transport.connector_store import HeldUiProfiles, OpenableProfile
from agent_comms.transport.tailnet_buses import PeerBus
from agent_comms.transport.tailnet_profiles import AskedPeer, HoldingPeerProfile, TailnetProfiles
from agent_comms.transport.tools.tailnet import CommsTailnetBusesTool, CommsTailnetProfileTool
from formbridge.operations import ExclusiveKind, OperationKind
from objectstate import ObjectState, ObjectStateRegistry

from toad.application_lifetime import ApplicationLifetime, ApplicationStart
from toad.client import bus_connect
from toad.client.bus_selection import (
    BusChoice,
    BusesFound,
    BusPickerHost,
    HeldBus,
    TailnetAnswer,
    TailnetUnanswered,
)
from toad.client.connection import CoreConnection
from toad.client.db import DB
from toad.client.resource_release import AsyncResourceRelease
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


class PeerProfileRequest(OperationKind, ExclusiveKind):
    """Asks a tailnet peer for a profile to its bus; a newer ask replaces it."""


class BusDiscovery(OperationKind, ExclusiveKind):
    """Asks the tailnet which peers hold a bus; a newer ask, a picker the reader just
    opened, replaces the one running."""


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

    def open_held_profile(self, path) -> None:
        """Open the bus a newly-held profile names. Used by the bus-connect paste flow
        (`bus_connect._hold_pasted_profile`) after `HoldUiVerb` wrote the profile to the
        held directory. Reports through the warning channel when the held file is not
        openable, mirroring the failure path in `asked_peer` so a bad paste does not raise."""
        match HeldUiProfiles.entry(path, time.time()):
            case OpenableProfile() as openable:
                self.open_bus(HeldBus(openable))
            case held:
                self.show_warning(
                    f"Pasted profile cannot open its bus: {held.label()}", "Bus",
                )

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

    def ask_peer_for_profile(self, found: PeerBus) -> None:
        """Ask a discovered peer to hand over a profile, then open its bus."""
        self.run_operation(PeerProfileRequest, partial(self.asked_for_profile, found))

    async def asked_for_profile(self, found: PeerBus) -> None:
        """The ask runs in a thread: it is one ssh call to another machine, which on the UI
        loop would hold every frame for as long as that machine takes to answer."""
        try:
            asked = await self.preparation.run_thread(self.hold_peer_profile, found)
        except (OSError, ValueError, RuntimeError) as error:
            self.show_warning(str(error), "Bus")
            return
        self.asked_peer(asked)

    def hold_peer_profile(self, found: PeerBus) -> AskedPeer:
        core = self.coordination_access.open_current().core
        answer = core.call(CommsTailnetProfileTool(found=found, previous=TailnetProfiles.held_grants(found)))
        return answer.hold()

    def asked_peer(self, asked: AskedPeer) -> None:
        """What the peer answered: its bus, or the structured remediation for its refusal.

        A handed-over profile opens its bus directly; a refusal or non-answer goes through
        `BusConnectDecision.decision_for`, so the frontend offers tappable options
        (copy the setup command, paste a profile) instead of a shell-command banner the
        phone user cannot act on. The held family still gates openability — a fresh profile
        that reads back expired or unreadable is reported to the host's warning channel
        rather than treated as a success.
        """
        match asked:
            case HoldingPeerProfile(path=path):
                match HeldUiProfiles.entry(path, time.time()):
                    case OpenableProfile() as openable:
                        self.open_bus(HeldBus(openable))
                    case held:
                        self.show_warning(f"{asked.found.peer.name} handed over a profile this "
                                          f"machine cannot open: {held.label()}", "Bus")
            case _:
                self.offer_bus_connect(bus_connect.decision_for(asked, self))

    def tailnet_buses(self) -> tuple[PeerBus, ...]:
        """What the observed Core's tailnet reports on every peer: seconds of ssh, so it is
        called from a thread."""
        return self.coordination_access.open_current().core.call(CommsTailnetBusesTool()).peers

    def discover_buses(self) -> None:
        """Ask the tailnet which peers hold a bus, for every bus listing.

        Every frontend asks once when its window opens, so the welcome lists the tailnet's
        buses without sweeping it each time the welcome shows, and a picker the reader opens
        to choose asks again. Until the answer, each listing shows the last one
        (found_buses); the ssh sweep runs on the observed Core's machine, not this one.
        """
        self.run_operation(BusDiscovery, self.ask_tailnet)

    async def ask_tailnet(self) -> None:
        await self.wait_operations(ApplicationStart)
        try:
            found = await self.preparation.run_thread(self.tailnet_buses)
        except (OSError, ValueError, RuntimeError) as error:
            self.tailnet_answered(TailnetUnanswered(str(error)))
            return
        self.found_buses = found
        self.tailnet_answered(BusesFound(found))

    @abstractmethod
    def tailnet_answered(self, answer: TailnetAnswer) -> None:
        """Show ``answer`` in each bus listing this frontend has open."""

    async def close_client(self) -> None:
        """Release the launch's client owners in the order they depend on each other:
        running operations first, then thread work and navigation, the observation's
        updates, the native views, the navigation reader, rendering, and the coordination
        access last. Accepted
        preparation survives its UI waiter, so the observer stays available until those
        workers and their read replies finish."""
        async with AsyncResourceRelease() as release:
            release.push_async_callback(self.coordination_access.close)
            release.push_async_callback(self.close_rendering)
            release.push_async_callback(self.navigation_reader.aclose)
            release.push_async_callback(self.close_native_views)
            release.push_async_callback(self.coordination_access.stop_observing)
            release.push_async_callback(self.thread_actions.close)
            release.push_async_callback(self.thread_navigation.close)
            release.push_async_callback(self.end_operations)

    @abstractmethod
    async def close_native_views(self) -> None:
        """Close this frontend's views of the open tabs; the tabs stay saved."""

    @abstractmethod
    async def close_rendering(self) -> None:
        """Join this frontend's render work and stop its render processes."""

    @abstractmethod
    def connection_for(self, choice: BusChoice) -> CoreConnection:
        """The connection ``choice`` names, read by the parser this frontend launches with."""

    def start_client(self) -> None:
        """How every frontend starts: observe the connection's Core, checking its route
        once a second so a bus that drops (an install restarting Core, a network blip) or
        changes opens again on the next check and every subscribed view rebinds to it; then
        this frontend's own start, and one ask of the tailnet for its bus listings. Each frontend once wrote this sequence itself, and the Qt
        copy left out the route check, so a dropped bus never came back on the phone."""
        self.coordination_access.start()
        self.begin_frontend()
        self.discover_buses()

    @abstractmethod
    def begin_frontend(self) -> None:
        """This frontend's own start, after observation begins: its window and saved tabs."""

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
