"""Textual-facing: picking a bus switches the running app onto it, in place."""

import time
from pathlib import Path

import pytest

from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.nominal.field_codec import RootId
from agent_comms.transport.connector_profile import (
    BearerSecret,
    HttpsMcpEndpoint,
    ReachedRoute,
    UiConnectionProfile,
    UiCredential,
    UiGrantId,
)
from agent_comms.transport.connector_store import HeldUiProfiles, OpenableProfile
from agent_comms.transport.tailnet_buses import (
    NamedHost,
    PeerHoldsBus,
    TailnetBuses,
    TailnetPeer,
)
from agent_comms.transport.tailnet_profiles import (
    OfferedPeerProfile,
    PeerRefusedProfile,
    TailnetProfiles,
)
from textual.css.scalar import Unit
from yarl import URL

from toad.app import ToadApp
from toad.application_outcome import Ended, Succeeded
from toad.client.application import BusDiscovery, BusSwitch
from toad.client.bus_selection import BusChoice, DiscoveredPeer, HeldBus, LocalBus
from toad.client.connection import FailedObservation, LocalObserving, RemoteCoreConnection
from toad.client.db import TabScope
from toad.screens.bus_choice import BusAddress, BusChoices, BusPanel, BusRows
from toad.client.application_actions import ApplicationAction
from support.roots import Roots
from support.tailnet import FakeTailnet


@pytest.fixture
def tailnet() -> FakeTailnet:
    """The tailnet this test's processes see (Roots.tailnet), empty until a test holds a
    peer on it."""
    return Roots.of_this_process().tailnet


def openable(path: Path) -> OpenableProfile:
    """A held profile built through its own constructors, as the connector writes one."""
    return OpenableProfile(path, UiConnectionProfile(
        HttpsMcpEndpoint(URL("https://box-b.example/mcp")),
        UiCredential(UiGrantId.mint(), RootId.mint(), expires_at=2e9, token=BearerSecret("t0ken")),
    ))


def test_a_chosen_bus_is_the_only_one_the_next_launch_names(tmp_path):
    """One launch opens one bus: choosing replaces any profile the current launch carries."""
    carried = ("--comms-profile", "/held/old.json", "--theme", "dark")
    assert LocalBus().arguments(carried) == ("--theme", "dark")
    chosen = openable(tmp_path / "box-b.json")
    assert HeldBus(chosen).arguments(carried) == (
        "--theme", "dark", "--comms-profile", str(tmp_path / "box-b.json"))
    assert HeldBus(chosen).arguments(()) == ("--comms-profile", str(tmp_path / "box-b.json"))
    assert LocalBus().arguments(()) == ()


def test_a_profile_names_its_host_and_namespace_in_the_picker(tmp_path):
    chosen = openable(tmp_path / "box-b.json")
    assert HeldBus(chosen).label().startswith("box-b.example · ")
    assert LocalBus().label() == "This machine"
    assert BusChoice.offered(0.0)[0] == LocalBus(), "this machine's own bus is always offered first"


async def test_picking_a_bus_switches_the_running_app_onto_it(workspace, monkeypatch, tmp_path):
    """Tristan: "we should factor that shit out properly so we don't reload the whole app for
    a simple bus change". The same app and the same coordination access observe the chosen
    Core; the tab roster moves to its location; nothing exits. Choosing this machine again
    comes back the same way, read by the launch parser from the launch's own arguments."""
    held = tmp_path / "box-b.json"
    openable(held).profile.write_new(held)
    monkeypatch.setattr("sys.argv", ["toad", "--comms-root", str(workspace.launch_root.path)])
    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        access, local = app.coordination_access, app.coordination_access.connection
        saved = app.tab_order.names
        assert saved, "the fixture's session is a tab saved under this machine's bus"
        app.picked_bus(HeldBus(openable(held)))
        await app.wait_operations(BusSwitch)
        assert isinstance(access.observation, FailedObservation), (
            "the unreachable bus is observed, and refused, in place")
        assert app.coordination_access is access, "one access; its views stay subscribed"
        assert access.connection.location == "https://box-b.example/mcp"
        assert app.tab_order.scopes == (TabScope("https://box-b.example/mcp"),)
        assert app.tab_order.names == () and not app.session_navigation.members, (
            "the views of the bus left behind are closed")
        assert isinstance(app.return_value, Ended), "the app is still running"

        app.picked_bus(LocalBus())
        await app.wait_operations(BusSwitch)
        assert isinstance(access.observation, LocalObserving), "this machine's bus, observed again"
        assert access.connection.location == local.location
        assert access.connection is not local, "read again by the launch parser"
        assert app.tab_order.scopes == local.tab_scopes()
        assert app.tab_order.names == saved, "its saved tabs stayed saved and open again"
        assert isinstance(app.return_value, Ended)


async def test_a_dismissed_picker_changes_nothing(workspace):
    """Through the fixture that owns a running app: the earlier hand-built ToadApp here was
    the only test that let one close on its own, and it died in application start."""
    async with workspace.app(size=(140, 48)) as ui:
        connection = ui.app.coordination_access.connection
        ui.app.picked_bus(None)
        await ui.step()
        # Esc out of the picker leaves this session on its own bus.
        assert ui.app.coordination_access.connection is connection


def test_an_upgrade_reopens_this_launchs_own_arguments(monkeypatch):
    """Succeeded execs the runtime it switched to with this launch's arguments, bus and all."""
    monkeypatch.setattr("sys.argv", ["toad", "--comms-profile", "/held/old.json", "--theme", "dark"])
    assert Succeeded(LaunchRuntime.running()).arguments() == (
        "--comms-profile", "/held/old.json", "--theme", "dark")


async def test_the_hamburger_offers_the_picker_under_its_own_name(workspace):
    """One declaration, both doors: the key and the menu entry are the same action, so the
    menu cannot offer a command the keymap does not know."""
    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        offered = {type(command).__name__: label for command, label in ApplicationAction.menu(app)}
        assert offered["OpenBusAction"] == "Switch bus (local or remote)"


async def test_the_picker_waits_for_a_pick_instead_of_taking_its_first_row(workspace):
    """Tristan: "I see the window come up and then it immediately loads the local bus again".

    A Select posts Changed when its initial value is set, so a picker that acts on every
    Changed chooses its own first row before the reader has read it.
    """

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        connection = app.coordination_access.connection
        app.push_screen(BusChoices(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        for _ in range(4):
            await ui.step()
        assert isinstance(app.screen, BusChoices), "the picker stays up until a row is chosen"
        assert app.coordination_access.connection is connection, "nothing is opened by showing a list"


async def test_the_picker_adds_the_tailnet_peers_it_finds(workspace, monkeypatch, tmp_path, tailnet):
    """Tristan: "it only detects this machine shohld detect gaming desktop".

    The dialog opens on what this machine knows with what the window's own ask found, and
    asks the tailnet again: what matters is that a found peer becomes a row named by what it
    holds.
    """


    # This machine's own held profiles are not this test's subject, and a real one in the
    # owner's home would be a row here.
    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        # The window asked once when it opened and found nobody; the peers join after, so
        # only the picker's own ask can find them.
        await app.wait_operations(BusDiscovery)
        tailnet.hold(TailnetPeer("ts-gaming", "100.119.57.99", True), 43)
        tailnet.hold(TailnetPeer("desktop", "100.124.133.120", True), 247)
        tailnet.held.touch()
        app.push_screen(BusChoices(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        picker = app.screen
        await ui.until(lambda: bool(picker.query(BusRows)), why="the picker to compose")
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus"], "instant rows first"
        tailnet.held.unlink()
        await ui.until(lambda: len(picker.rows) == 3, why="the tailnet peers to arrive")
        # Tailscale's peers in the order discovery lists them: by name.
        assert [row.label() for row in picker.rows[1:]] == [
            "desktop · 247 threads", "ts-gaming · 43 threads"]
        assert all(isinstance(row, DiscoveredPeer) for row in picker.rows[1:])


async def test_picking_a_peer_asks_it_for_a_profile_and_opens_its_bus(workspace, monkeypatch, tmp_path):
    """Tristan: "it's a bus on my private tailnet why would want to have to jupm throuhg hoops".

    The ask is one ssh call to that machine's own connector, stubbed here; what matters is
    that picking the row opens the bus the peer handed over, with no errand in between. The
    switch itself is test_picking_a_bus_switches_the_running_app_onto_it's; opening here is
    recorded, so the test never dials the real machine the profile names.
    """

    found = PeerHoldsBus(TailnetPeer("ts-gaming", "100.119.57.99", True), 43)
    profile = UiConnectionProfile(
        HttpsMcpEndpoint(URL("https://ts-gaming.tail553874.ts.net:8443/mcp")),
        UiCredential(UiGrantId("b" * 32), RootId("0" * 32), time.time() + 3600,
                     BearerSecret("secret")),
        ReachedRoute("100.119.57.99"))
    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    held = tmp_path / "ts-gaming.json"
    monkeypatch.setattr(TailnetBuses, "peers", classmethod(lambda cls: (found.peer,)))
    monkeypatch.setattr(TailnetProfiles, "ask",
                        classmethod(lambda cls, peer, previous: OfferedPeerProfile(peer, profile)))

    opened: list[BusChoice] = []
    monkeypatch.setattr(ToadApp, "open_bus", lambda self, choice: opened.append(choice))

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        DiscoveredPeer(found).chosen(app)
        await ui.until(lambda: opened, why="the peer's bus to be opened")
        [choice] = opened
        assert isinstance(choice, HeldBus)
        assert str(choice.profile.profile.endpoint.url).endswith(":8443/mcp")
        assert choice.arguments(())[-2:] == (RemoteCoreConnection.argument, str(held)), (
            "the switch reads the profile the peer handed over")


async def test_a_peer_that_refuses_says_so_in_its_own_words(workspace, monkeypatch):
    """A public endpoint refuses, and the reason belongs on screen, not in a log."""

    found = PeerHoldsBus(TailnetPeer("ts-gaming", "100.119.57.99", True), 43)
    monkeypatch.setattr(TailnetBuses, "peers", classmethod(lambda cls: (found.peer,)))
    monkeypatch.setattr(TailnetProfiles, "ask", classmethod(
        lambda cls, peer, previous: PeerRefusedProfile(peer, "No tailnet-only endpoint serves 127.0.0.1:18766")))

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        connection = app.coordination_access.connection
        said: list[str] = []
        monkeypatch.setattr(type(app), "notify",
                            lambda self, message, **options: said.append(message))
        DiscoveredPeer(found).chosen(app)
        await ui.until(lambda: said, why="the peer's refusal on screen")
        assert "would not hand out a profile" in said[0]
        assert "No tailnet-only endpoint" in said[0], "the peer's own sentence, not a summary"
        assert app.coordination_access.connection is connection


async def test_a_machine_this_one_holds_a_profile_for_is_one_row(workspace, monkeypatch, tmp_path, tailnet):
    """Tristan: "histiry of last connected accunukates in the remote bus dialog".

    A held profile and a discovered peer were two rows for one machine: one named by its
    certificate and grant id, one by its hostname and thread count. The found row wins,
    because it says which machine and how much is on it.
    """


    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    for address, name in (("100.119.57.99", "ts-gaming"), ("100.112.213.110", "pixel-8a")):
        UiConnectionProfile(
            HttpsMcpEndpoint(URL(f"https://{name}.tail553874.ts.net:8443/mcp")),
            UiCredential(UiGrantId(f"{ord(name[0]):02x}" * 16), RootId("0" * 32), time.time() + 3600,
                         BearerSecret("secret")),
            ReachedRoute(address),
        ).write_new(tmp_path / f"{name}.json")

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        await app.wait_operations(BusDiscovery)
        tailnet.hold(TailnetPeer("ts-gaming", "100.119.57.99", True), 43)
        tailnet.held.touch()
        app.push_screen(BusChoices(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        picker = app.screen
        await ui.until(lambda: bool(picker.query(BusRows)), why="the picker to compose")
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus", "HeldBus", "HeldBus"]
        tailnet.held.unlink()
        await ui.until(lambda: any(isinstance(row, DiscoveredPeer) for row in picker.rows),
                       why="the tailnet peer to arrive")
        kinds = [type(row).__name__ for row in picker.rows]
        assert kinds == ["LocalBus", "HeldBus", "DiscoveredPeer"], (
            f"the held row for the found machine is replaced, not stacked beside it: {kinds}")
        # The one held row left is the machine the tailnet did not report.
        held = next(row for row in picker.rows if isinstance(row, HeldBus))
        assert "pixel-8a" in held.label()
        assert picker.rows[-1].label() == "ts-gaming · 43 threads"


def test_a_dialog_fits_a_narrow_window():
    """Tristan: "the remote buf dialog isnt mobike layout fridnely cant be narrow enough"."""


    panel = BusPanel()
    panel.apply_native_layout()
    assert panel.styles.width.unit is Unit.WIDTH, (
        f"a fixed {panel.styles.width} cannot fit a phone-width window")
    assert panel.styles.max_width.value == 72, "and it still stops growing on a wide one"


async def test_discovery_asks_the_observed_core_and_never_holds_the_message_pump(
        workspace, monkeypatch, tmp_path, tailnet):
    """A terminal without tailscale still paints while its observed Core discovers peers."""

    def no_terminal_cli(cls):
        raise AssertionError("The terminal has no tailscale CLI; ask the observed Core")

    monkeypatch.setattr(TailnetBuses, "seen", classmethod(no_terminal_cli))
    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    tailnet.hold(TailnetPeer("discovered", "100.64.1.2", True), 9)
    tailnet.held.touch()
    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        app.push_screen(BusChoices(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        picker = app.screen
        for _ in range(4):
            await ui.step()
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus"], (
            "the picker paints and answers while the peer is still slow to say what it holds")
        tailnet.held.unlink()
        await ui.until(lambda: len(picker.rows) == 2, why="the slow peer to answer")
        assert picker.rows[-1].label() == "discovered · 9 threads"
        assert app.found_buses, "the answer is the application's, for every listing"


async def test_a_typed_address_is_asked_exactly_as_a_discovered_peer_is(workspace, monkeypatch, tmp_path):
    """Tristan, UX 10: let a bus be added by hand - type an address, save it, and be able
    to remove saved ones again.

    Typing runs the same ask-for-profile flow a discovered peer runs, so there is no
    second way into a bus: the host hands a profile over and it becomes an ordinary held
    row, which is also where saving and removing come from.
    """


    asked: list[object] = []
    profile = UiConnectionProfile(
        HttpsMcpEndpoint(URL("https://typed-host.example:8443/mcp")),
        UiCredential(UiGrantId("c" * 32), RootId("0" * 32), time.time() + 3600,
                     BearerSecret("secret")),
        ReachedRoute("typed-host.example"))

    def offer(cls, peer, previous):
        asked.append(peer)
        return OfferedPeerProfile(peer, profile)

    # Typing names a peer Core's own tailnet reports; it is never an arbitrary ssh
    # destination, which the served tool's own guard refuses (Core
    # test_a_typed_address_must_name_a_peer_core_already_reports holds that half).
    typed = TailnetPeer("typed-host", "100.64.9.9", True)
    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(TailnetBuses, "peers", classmethod(lambda cls: (typed,)))
    monkeypatch.setattr(TailnetProfiles, "ask", classmethod(offer))

    async with workspace.app(size=(140, 48)) as ui:
        app, pilot = ui.textual
        app.push_screen(BusChoices(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        picker = app.screen
        await ui.until(lambda: bool(picker.query(BusAddress)), why="the picker to compose")
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus"]

        field = picker.query_one(BusAddress)
        field.focus()
        await ui.type("typed-host")
        await ui.press("enter")
        await ui.until(lambda: asked, why="the typed host to be asked for a profile")
        # Resolved to Core's own peer, not to the text: the same ask, and the same
        # destination a discovered row would have reached.
        assert [entry.peer for entry in asked] == [typed]
        assert isinstance(asked[0], NamedHost), "the member a typed address is"
        assert field.value == "", "the field clears once its host is asked"


async def test_a_saved_bus_can_be_forgotten_and_its_profile_goes_with_it(workspace, monkeypatch, tmp_path):
    """Removing a saved bus is removing the profile that saved it; HeldUiProfiles lists
    exactly that directory, so there is no second record of what is saved."""

    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    held = tmp_path / "box-b.json"
    openable(held).profile.write_new(held)

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        app.push_screen(BusChoices(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        picker = app.screen
        await ui.until(lambda: bool(picker.query(BusRows)), why="the picker to compose")
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus", "HeldBus"]
        assert held.is_file()

        rows = picker.query_one(BusRows)
        rows.highlighted = 1
        address = picker.query_one(BusAddress)
        address.focus()
        await ui.type("ab")
        await ui.press("home", "delete")
        assert address.value == "b", "Delete edits the address before the picker sees it"
        assert held.is_file(), "editing an address must not forget the highlighted saved bus"

        rows.focus()
        rows.highlighted = 0
        await ui.press("delete")
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus", "HeldBus"], (
            "this machine's own bus is a fact, not a saved row, so Delete leaves it alone"
        )
        assert held.is_file()

        rows.highlighted = 1
        await ui.press("delete")
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus"]
        assert not held.exists(), "forgetting a saved bus removes the profile that saved it"
        await ui.press("escape")
        await ui.until(lambda: not isinstance(app.screen, BusChoices), why="Escape to close the picker")
