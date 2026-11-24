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
import json
import time
from abc import abstractmethod
from collections.abc import Awaitable, Iterable
from functools import cached_property, partial
from typing import TYPE_CHECKING, ClassVar

from agent_comms.nominal.field_codec import AcpSessionId, NoAcpSessionId
from agent_comms.transport.connector_store import HeldUiProfiles, OpenableProfile
from agent_comms.transport.tailnet_buses import PeerBus
from agent_comms.transport.tailnet_profiles import AskedPeer, HoldingPeerProfile, TailnetProfiles
from agent_comms.transport.tools.tailnet import CommsTailnetBusesTool, CommsTailnetProfileTool
from formbridge.operations import ExclusiveKind, OperationKind
from objectstate import ObjectState, ObjectStateRegistry

from toad.client.pending import BusConnecting, awaited
from toad.application_lifetime import ApplicationLifetime, ApplicationStart
from toad.heap import HEAP
from toad.client import bus_connect
from toad.client.bus_selection import (
    BusChoice,
    BusesFound,
    BusPickerHost,
    HeldBus,
    TailnetAnswer,
    TailnetUnanswered,
)
from toad.client.agent_processes import AgentProcesses
from toad.client.connection import CoreConnection
from toad.client.db import DB
from toad.client.input_attention import InputAttention
from toad.client.resource_release import AsyncResourceRelease
from toad.client.session_tracker import OpenTab, SessionTracker, SidebarState
from toad.client.tab_order import TabOrder
from toad.constants import WELCOME
from toad.core import events as core_events
from toad.core import session_requests
from toad.launch_binding import AgentBinding
from toad.launch_opening import LaunchOpening, NoLaunchOpening
from toad.navigation_preparation import NavigationReader
from toad.render_backend import PreparedRenderer
from toad.session_host import NavigationHost
from toad.session_navigation import SessionNavigation
from toad.setting_declarations import Effect
from toad.sidebar_layout import SidebarLayout
from toad.terminal_origin import TerminalOrigin
from toad.thread_actions import ThreadActions
from toad.thread_navigation import ThreadNavigator

if TYPE_CHECKING:
    from toad.preferences import SavedSettings, ToadSettings


class SettingsKept(OperationKind, ExclusiveKind):
    """Writes the settings in use to their file after a change meant to outlive the run;
    a newer change's write replaces one still running."""


@awaited(BusConnecting)
class BusSwitch(OperationKind):
    """Switches the application onto a bus the reader chose."""


class PeerProfileRequest(OperationKind, ExclusiveKind):
    """Asks a tailnet peer for a profile to its bus; a newer ask replaces it."""


class BusDiscovery(OperationKind, ExclusiveKind):
    """Asks the tailnet which peers hold a bus; a newer ask, a picker the reader just
    opened, replaces the one running."""


class ClientApplication(BusPickerHost, NavigationHost):
    """One launch's client state and its session operations, shared by every frontend.

    Owns toolkit-neutral access to `ToadSettings` via `settings` / `saved_settings` /
    `configuration_state`. Every frontend inherits the same accessor; `QtToadApp` gets
    `app.settings.sidebar.unread_counts.badge(...)` for free, the same way Textual's
    `ThemedApp` already did. On the Textual app, `ThemedApp.__init__` still assigns
    `saved_settings` eagerly before `TextualColours` reads diff settings during
    colour-system construction; that assignment flows through the setter here.
    """

    input_attention: InputAttention
    """The title that blinks while input is required; each frontend sets its own."""

    def history_displayed(self) -> None:
        """A view's history was painted, in either frontend: the process's heap hears it
        (`toad.heap`). Only Textual's app told it until 2026-11-22; Qt's heap was never frozen
        after its startup."""
        HEAP.history_displayed()

    _saved_settings: SavedSettings | None = None

    @property
    def saved_settings(self) -> SavedSettings:
        """The settings holder this launch reads and writes. Lazily opened on first
        access so Qt (which has no pre-constructor settings hook) doesn't need to
        know to allocate it; Textual's `ThemedApp.__init__` sets it eagerly for the
        colour-system construction order."""
        if self._saved_settings is None:
            self._saved_settings = self.open_settings()
            ObjectStateRegistry.register(self._saved_settings.state)
        return self._saved_settings

    @saved_settings.setter
    def saved_settings(self, value: SavedSettings) -> None:
        if self._saved_settings is value:
            return
        self._saved_settings = value
        ObjectStateRegistry.register(value.state)

    def open_settings(self) -> SavedSettings:
        """The settings file every frontend reads at launch and writes on a change; each
        change applies its `Effect` through `apply_setting_effect`, so a setting changed in
        either frontend's settings screen repaints what it reaches at once. A frontend
        applies them all once its widgets exist (`SavedSettings.apply_all`)."""
        from toad.preferences import SavedSettings
        path = SavedSettings.path()
        raw = json.loads(path.read_text("utf-8")) if path.exists() else {}
        return SavedSettings(raw, applied=self.apply_setting_effect, report_error=self.settings_not_saved)

    def settings_not_saved(self, error: Exception) -> None:
        self.show_error(error, "Settings")

    def apply_setting_effect(self, field) -> None:
        """An app-wide setting changed: its `Effect` repaints the open widgets it reaches,
        each reading through its nearest settings scope (a view's override still wins).

        One setting's effect failing does not stop the others: `SavedSettings.apply_all` runs
        every setting through here as the app starts, and a single raise there would leave the
        app unable to open (2026-11-18: a saved theme Qt could not draw stopped the phone app at
        every launch). The failure is shown and saved by the app's error owner (`show_error`,
        which writes it to logs/errors), titled by the setting, and the setting's value stays."""
        if (effect := field.metadata(Effect)) is None:
            return
        try:
            effect.apply(self, field)
        except Exception as error:
            self.show_error(error, f"Setting {field.path.value}")

    @abstractmethod
    def settings_widgets(self, widget_type: type) -> Iterable:
        """This app's open widgets composing ``widget_type``, a capability a setting's
        `Effect` reaches (`Effect.open_widgets`) to repaint by the changed setting."""

    @abstractmethod
    def follow_wheel_scroll_rows(self) -> None:
        """A mouse wheel notch now scrolls `ui.wheel_scroll_rows` rows."""

    @abstractmethod
    def follow_theme(self) -> None:
        """Draw everything in the `ui.theme` scheme now named."""

    @abstractmethod
    def follow_key_mode(self) -> None:
        """Every input editor and key binding follows the `ui.key_mode` now chosen."""

    @abstractmethod
    def follow_keymap(self) -> None:
        """Every command answers the keys `ui.keymap` now gives it (its defaults otherwise)."""

    @abstractmethod
    def follow_line_renderer(self) -> None:
        """The `diff` settings changed: lines draw by them from now on, open ones again."""

    def update_show_sessions(self) -> None:
        """The session tabs show as `ui.sessions_bar` says for this many open tabs."""
        self.show_session_tabs(self.settings.ui.sessions_bar.shown(len(self.open_tabs)))

    @abstractmethod
    def show_session_tabs(self, shown: bool) -> None:
        """Show or hide the session tabs; the open tabs draw with the current unread badge."""

    @property
    def settings(self) -> ToadSettings:
        """The settings in use, to read from; `saved_settings` changes and saves them."""
        return self.saved_settings.current

    @property
    def sidebar_show_stopped(self) -> bool:
        """The sidebar's stopped filter, from the one `sidebar.show_stopped` setting both
        frontends read."""
        return self.settings.sidebar.show_stopped

    @property
    def sidebar_show_archived(self) -> bool:
        return self.settings.sidebar.show_archived

    @property
    def configuration_state(self) -> ObjectState:
        """The ObjectState backing `settings`; on the app the nearest `SettingsScope`
        resolves to this, so `SettingsReader`-based widgets reach the same object."""
        return self.saved_settings.state

    def _make_render_processes(self):
        """The renderer every frontend submits preparation work to. The default wraps this
        launch's shared `PreparationRuntime`; a frontend whose consumer owns per-thread
        context (Textual's message pump and Worker) overrides this to wrap it so detached
        work never borrows those contexts. Hoisting the attribute here so both frontends
        answer `app.render_processes` the same way, replacing the Qt app that had none and
        the TUI app that set its own (`ToadApp.__init__`, which `WireHistory` and the draft
        renderer already submitted through)."""
        return PreparedRenderer(self.preparation)

    def initialize_client(
        self,
        agent_binding: AgentBinding,
        connection: CoreConnection,
        agent_session_id: AcpSessionId | NoAcpSessionId = NoAcpSessionId(),
        opening: LaunchOpening = NoLaunchOpening(),
    ) -> None:
        """The launch's client owners, built once from the native constructor.

        The renderer starts here, before any view asks it to prepare a page: a process pool
        spawned lazily by the first page read held every frontend's first transcript blank
        for its workers' startup (3.7 s on desktop Qt, which never started it). The native
        constructor runs before a terminal captures stderr, which spawn bookkeeping needs."""
        self.preparation.renderer.start()
        self.render_processes = self._make_render_processes()
        self.events = core_events.CoreEventStream(self)
        self.navigation_reader = NavigationReader()
        self.agent_binding = agent_binding
        self.application = self.lifetime_kind(self, agent_session_id, opening)
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
        # Every frontend acts on the workspace requests published on the navigator.
        self.session_navigation.bind_events()
        # One switch at a time: a second pick waits for the first to finish moving the owners.
        self.bus_switching = asyncio.Lock()

    def open_bus(self, choice: BusChoice) -> None:
        """Switch this session onto a bus the reader picked."""
        self.run_operation(BusSwitch, partial(self.switch_bus, choice))

    def open_held_profile(self, path) -> None:
        """Open the bus a newly-held profile names. Used by the bus-connect paste flow
        (`bus_connect._hold_pasted_profile`) after `hold_ui_profile` wrote the profile to
        the held directory. Reports through the warning channel when the held file is not
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

    lifetime_kind: ClassVar[type[ApplicationLifetime]] = ApplicationLifetime
    """What this frontend's start, background and end do; the terminal app adds its own."""

    @property
    def agent_processes(self) -> AgentProcesses:
        """Whether agent processes start here: the Core connection decides."""
        return self.coordination_access.connection.agent_processes

    @cached_property
    def sidebar_layout(self) -> SidebarLayout:
        """The one placement owner of this terminal's sidebars, kept in the settings file
        with every other setting, so an arrangement outlives the run in every frontend."""
        return SidebarLayout(self.saved_settings, TerminalOrigin.of(),
                             alone=lambda: self.selected_mode == WELCOME)

    def keep_settings(self) -> None:
        """A change meant for the next start (a sidebar moved, resized, folded) reaches the
        settings file now, not only at a quit the platform may never send."""
        self.run_operation(SettingsKept, self.saved_settings.save)

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
            release.push_async_callback(self.application.ended)

    @abstractmethod
    async def close_native_views(self) -> None:
        """Close this frontend's views of the open tabs; the tabs stay saved."""

    async def close_rendering(self) -> None:
        """Join this launch's render work and stop its render processes: the renderer every
        frontend submits to (`render_processes`) ends its submissions, then the preparation
        runtime under it closes. Textual's app closed the renderer; Qt's closed the runtime
        directly and left the renderer's submissions open (2026-11-22: NRA's
        sibling-override-step finding)."""
        await self.render_processes.aclose()

    @abstractmethod
    def connection_for(self, choice: BusChoice) -> CoreConnection:
        """The connection ``choice`` names, read by the parser this frontend launches with."""

    def start_client(self) -> None:
        """How every frontend starts: observe the connection's Core, checking its route
        once a second so a bus that drops (an install restarting Core, a network blip) or
        changes opens again on the next check and every subscribed view rebinds to it; then
        this frontend's own start, and one ask of the tailnet for its bus listings. Each frontend once wrote this sequence itself, and the Qt
        copy left out the route check, so a dropped bus never came back on the phone.

        First, work on this loop that fails with nobody waiting for it is shown from now on
        (`CommsHost.hear_lost_failures`), in both frontends: the Qt start alone asked for
        it at first, and a frontend that does not ask keeps such failures to itself."""
        self.hear_lost_failures()
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

    # Hamburger-menu capabilities: a frontend with a real screen for each overrides
    # these to push its screen; frontends without one inherit the default notice so
    # the menu entry still appears and tells the user it's not yet available on this
    # toolkit. Keeping the capability on ClientApplication (not on the Action class)
    # lets `ApplicationAction.menu(app)` list the same items on every frontend; the
    # per-frontend screen is behind one polymorphic call, not a parallel class tree.

    def open_bus_switcher(self) -> None:
        """Open the bus picker (local or remote). Textual's `ToadApp` pushes
        `BusChoices`; Qt will get its own picker — stub notice meanwhile."""
        self.show_info("Bus picker is not yet available on this frontend.",
                       "Switch bus")

    async def edit_settings(self) -> None:
        """Edit persistent application preferences. Textual pushes `SettingsScreen`
        and saves on close; Qt will get its own editor — stub notice meanwhile."""
        self.show_info("Settings editor is not yet available on this frontend.",
                       "Settings")

    async def open_team_board(self) -> None:
        """Open the live team board. Textual pushes `TeamPage`; Qt stub notice."""
        self.show_info("Team board is not yet available on this frontend.",
                       "Team")

    async def open_keymap_browser(self) -> None:
        """Browse and change keybindings. Textual pushes `KeymapScreen`; Qt stub notice."""
        self.show_info("Keymap browser is not yet available on this frontend.",
                       "Keymap")

    @property
    def welcome_hints(self) -> str:
        """The gesture/shortcut hint line rendered below the welcome's row list.
        Textual overrides with its keyboard shortcuts; Qt overrides with touch
        gestures. Default raises so a frontend that forgets to override is loud,
        not silently blank.

        Mirrors the shape `WelcomeScreen.HINTS` carries on Textual at
        `src/toad/screens/welcome.py:242`; keeping it on the app (rather than
        on each Welcome screen class) means the content is owned per-frontend
        but called once from both Welcome implementations via `self.app.welcome_hints`."""
        raise NotImplementedError(
            f"{type(self).__name__} must override welcome_hints — the welcome's "
            f"hint line is frontend-specific (keyboard vs touch) and the default "
            f"raises rather than silently hiding the line."
        )

    @property
    def open_tabs(self) -> tuple[OpenTab, ...]:
        return self.session_navigation.tabs
