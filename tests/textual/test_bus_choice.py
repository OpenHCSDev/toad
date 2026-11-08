"""Textual-facing: picking a bus ends the app onto the launch that opens that bus."""

import asyncio
from pathlib import Path

from agent_comms.connector_profile import BearerSecret, HttpsMcpEndpoint, UiConnectionProfile, UiCredential, UiGrantId
from agent_comms.connector_store import OpenableProfile
from agent_comms.launch_runtime import LaunchRuntime
from agent_comms.nominal.field_codec import RootId
from agent_comms.repo import Checkout
from yarl import URL

from toad.app import ToadApp
from toad.widget_actions import ApplicationAction
from toad.application_outcome import Reconnected, Succeeded
from toad.comms_root import BusChoice, HeldBus, LocalBus, LocalCoreConnection
from toad.launch_binding import NoAgent


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


async def test_picking_a_bus_ends_the_app_onto_it(workspace, tmp_path):
    app = ToadApp(agent_binding=NoAgent(), project_dir=Checkout(workspace.project),
                  connection=LocalCoreConnection.from_launch(workspace.launch_root))
    choice = HeldBus(openable(tmp_path / "box-b.json"))
    async with app.run_test(size=(140, 48)):
        app.picked_bus(choice)

        async def ended() -> None:
            while not isinstance(app.return_value, Reconnected):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(ended(), 30)
    assert app.return_value == Reconnected(LaunchRuntime.running(), choice)


async def test_a_dismissed_picker_changes_nothing(workspace):
    """Through the fixture that owns a running app: the earlier hand-built ToadApp here was
    the only test that let one close on its own, and it died in application start."""
    async with workspace.app(size=(140, 48)) as ui:
        ui.app.picked_bus(None)
        await ui.step()
        # Esc out of the picker leaves this session on its own bus.
        assert not isinstance(ui.app.return_value, Reconnected)


def test_both_exec_outcomes_share_one_exec_and_differ_only_in_arguments(monkeypatch, tmp_path):
    """Succeeded keeps this launch's arguments; Reconnected rewrites them for its choice."""
    monkeypatch.setattr("sys.argv", ["toad", "--comms-profile", "/held/old.json", "--theme", "dark"])
    runtime = LaunchRuntime.running()
    assert Succeeded(runtime).arguments() == ("--comms-profile", "/held/old.json", "--theme", "dark")
    assert Reconnected(runtime, LocalBus()).arguments() == ("--theme", "dark")
    chosen = openable(tmp_path / "box-b.json")
    assert Reconnected(runtime, HeldBus(chosen)).arguments() == (
        "--theme", "dark", "--comms-profile", str(tmp_path / "box-b.json"))


async def test_the_hamburger_offers_the_picker_under_its_own_name(workspace):
    """One declaration, both doors: the key and the menu entry are the same action, so the
    menu cannot offer a command the keymap does not know."""
    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        offered = {type(command).__name__: label for command, label in ApplicationAction.menu(app)}
        # Derived from the declared name, so the menu cannot drift from the action.
        assert offered["OpenBusAction"] == "Open bus"


async def test_the_picker_waits_for_a_pick_instead_of_taking_its_first_row(workspace):
    """Tristan: "I see the window come up and then it immediately loads the local bus again".

    A Select posts Changed when its initial value is set, so a picker that acts on every
    Changed chooses its own first row before the reader has read it.
    """
    from toad.screens.bus_choice import BusChoices

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        app.push_screen(BusChoices.offered(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        for _ in range(4):
            await ui.step()
        assert isinstance(app.screen, BusChoices), "the picker stays up until a row is chosen"
        assert not isinstance(app.return_value, Reconnected), "nothing is opened by showing a list"


async def test_the_picker_adds_the_tailnet_peers_it_finds(workspace, monkeypatch, tmp_path):
    """Tristan: "it only detects this machine shohld detect gaming desktop".

    The dialog opens on what this machine knows and asks the tailnet after, so the probe is
    stubbed here: what matters is that a found peer becomes a row named by what it holds.
    """
    from agent_comms.tailnet_buses import PeerHoldsBus, TailnetBuses, TailnetPeer
    from toad.comms_root import DiscoveredPeer
    from toad.screens.bus_choice import BusChoices

    from agent_comms.connector_store import HeldUiProfiles

    found = (PeerHoldsBus(TailnetPeer("ts-gaming", "100.119.57.99", True), 43),
             PeerHoldsBus(TailnetPeer("desktop", "100.124.133.120", True), 247))
    monkeypatch.setattr(TailnetBuses, "seen", classmethod(lambda cls: found))
    # This machine's own held profiles are not this test's subject, and a real one in the
    # owner's home would be a row here.
    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        app.push_screen(BusChoices.offered(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        picker = app.screen
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus"], "instant rows first"
        await ui.until(lambda: len(picker.rows) == 3, why="the tailnet peers to arrive")
        assert [row.label() for row in picker.rows[1:]] == [
            "ts-gaming · 43 threads", "desktop · 247 threads"]
        assert all(isinstance(row, DiscoveredPeer) for row in picker.rows[1:])


async def test_picking_a_peer_asks_it_for_a_profile_and_opens_its_bus(workspace, monkeypatch, tmp_path):
    """Tristan: "it's a bus on my private tailnet why would want to have to jupm throuhg hoops".

    The ask is one ssh call to that machine's own connector, stubbed here; what matters is
    that picking the row ends this session onto the bus the peer handed over, with no errand
    in between.
    """
    import time
    from agent_comms.connector_profile import (
        BearerSecret, HttpsMcpEndpoint, ReachedRoute, UiConnectionProfile, UiCredential, UiGrantId,
    )
    from agent_comms.connector_store import HeldUiProfiles
    from agent_comms.nominal.field_codec import RootId
    from agent_comms.tailnet_buses import PeerHoldsBus, TailnetPeer
    from agent_comms.tailnet_profiles import OfferedPeerProfile, PeerRefusedProfile, TailnetProfiles
    from toad.comms_root import DiscoveredPeer, HeldBus
    from yarl import URL

    found = PeerHoldsBus(TailnetPeer("ts-gaming", "100.119.57.99", True), 43)
    profile = UiConnectionProfile(
        HttpsMcpEndpoint(URL("https://ts-gaming.tail553874.ts.net:8443/mcp")),
        UiCredential(UiGrantId("b" * 32), RootId("0" * 32), time.time() + 3600,
                     BearerSecret("secret")),
        ReachedRoute("100.119.57.99"))
    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    held = tmp_path / "ts-gaming.json"
    from agent_comms.tailnet_buses import TailnetBuses
    monkeypatch.setattr(TailnetBuses, "peers", classmethod(lambda cls: (found.peer,)))
    monkeypatch.setattr(TailnetProfiles, "ask",
                        classmethod(lambda cls, peer, previous: OfferedPeerProfile(peer, profile)))

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        DiscoveredPeer(found).chosen(app)
        await ui.until(lambda: isinstance(app.return_value, Reconnected),
                       why="the session to end onto the peer's bus")
        opened = app.return_value.choice
        assert isinstance(opened, HeldBus)
        assert str(opened.profile.profile.endpoint.url).endswith(":8443/mcp")
        from toad.comms_root import RemoteCoreConnection
        assert opened.arguments(("toad",))[-2:] == (RemoteCoreConnection.argument, str(held)), (
            "the next launch names the profile the peer handed over")


async def test_a_peer_that_refuses_says_so_in_its_own_words(workspace, monkeypatch):
    """A public endpoint refuses, and the reason belongs on screen, not in a log."""
    from agent_comms.tailnet_buses import PeerHoldsBus, TailnetPeer
    from agent_comms.tailnet_profiles import PeerRefusedProfile, TailnetProfiles
    from toad.comms_root import DiscoveredPeer

    found = PeerHoldsBus(TailnetPeer("ts-gaming", "100.119.57.99", True), 43)
    from agent_comms.tailnet_buses import TailnetBuses
    monkeypatch.setattr(TailnetBuses, "peers", classmethod(lambda cls: (found.peer,)))
    monkeypatch.setattr(TailnetProfiles, "ask", classmethod(
        lambda cls, peer, previous: PeerRefusedProfile(peer, "No tailnet-only endpoint serves 127.0.0.1:18766")))

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        said: list[str] = []
        monkeypatch.setattr(type(app), "notify",
                            lambda self, message, **options: said.append(message))
        DiscoveredPeer(found).chosen(app)
        await ui.until(lambda: said, why="the peer's refusal on screen")
        assert "would not hand out a profile" in said[0]
        assert "No tailnet-only endpoint" in said[0], "the peer's own sentence, not a summary"
        assert not isinstance(app.return_value, Reconnected)


async def test_a_machine_this_one_holds_a_profile_for_is_one_row(workspace, monkeypatch, tmp_path):
    """Tristan: "histiry of last connected accunukates in the remote bus dialog".

    A held profile and a discovered peer were two rows for one machine: one named by its
    certificate and grant id, one by its hostname and thread count. The found row wins,
    because it says which machine and how much is on it.
    """
    import time

    from agent_comms.connector_profile import (
        BearerSecret, HttpsMcpEndpoint, ReachedRoute, UiConnectionProfile, UiCredential, UiGrantId,
    )
    from agent_comms.connector_store import HeldUiProfiles
    from agent_comms.nominal.field_codec import RootId
    from agent_comms.tailnet_buses import PeerHoldsBus, TailnetBuses, TailnetPeer
    from toad.comms_root import DiscoveredPeer, HeldBus
    from toad.screens.bus_choice import BusChoices
    from yarl import URL

    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    for address, name in (("100.119.57.99", "ts-gaming"), ("100.112.213.110", "pixel-8a")):
        UiConnectionProfile(
            HttpsMcpEndpoint(URL(f"https://{name}.tail553874.ts.net:8443/mcp")),
            UiCredential(UiGrantId(f"{ord(name[0]):02x}" * 16), RootId("0" * 32), time.time() + 3600,
                         BearerSecret("secret")),
            ReachedRoute(address),
        ).write_new(tmp_path / f"{name}.json")
    found = (PeerHoldsBus(TailnetPeer("ts-gaming", "100.119.57.99", True), 43),)
    monkeypatch.setattr(TailnetBuses, "seen", classmethod(lambda cls: found))

    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        app.push_screen(BusChoices.offered(), app.picked_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        picker = app.screen
        assert [type(row).__name__ for row in picker.rows] == ["LocalBus", "HeldBus", "HeldBus"]
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
    from textual.css.scalar import Unit

    from toad.screens.bus_choice import BusPanel

    panel = BusPanel()
    panel.apply_native_layout()
    assert panel.styles.width.unit is Unit.WIDTH, (
        f"a fixed {panel.styles.width} cannot fit a phone-width window")
    assert panel.styles.max_width.value == 72, "and it still stops growing on a wide one"


async def test_discovery_uses_selected_core_and_never_holds_the_message_pump(monkeypatch):
    """A terminal without tailscale still paints while its selected Core discovers peers."""
    import threading
    from dataclasses import dataclass
    from textual.app import App
    from agent_comms.nominal.field_codec import FieldCodec
    from agent_comms.tailnet_buses import PeerHoldsBus, TailnetBuses, TailnetPeer
    from agent_comms.transport.request import CoreAccess
    from agent_comms.transport.tools.tailnet import CommsTailnetBusesTool, TailnetBusesRead
    from toad.screens.bus_choice import BusChoices

    started, release = threading.Event(), threading.Event()
    expected = TailnetBusesRead((PeerHoldsBus(TailnetPeer("discovered", "100.64.1.2", True), 9),))

    class RemoteAnswer(CoreAccess):
        def call(self, request):
            assert isinstance(request, CommsTailnetBusesTool)
            started.set()
            assert release.wait(5), "the test releases the remote answer after checking paint"
            return FieldCodec.decode(TailnetBusesRead, FieldCodec.encode(expected))

    @dataclass
    class SelectedCore:
        core: CoreAccess

        def open_current(self):
            return self

    class PickerHost(App):
        coordination_access = SelectedCore(RemoteAnswer())

    def no_terminal_cli(cls):
        raise AssertionError("The terminal has no tailscale CLI; ask the selected Core")

    monkeypatch.setattr(TailnetBuses, "seen", classmethod(no_terminal_cli))
    app = PickerHost()
    try:
        async with app.run_test(size=(44, 28)) as pilot:
            picker = BusChoices(())
            app.push_screen(picker)
            assert await asyncio.to_thread(started.wait, 3)
            painted = asyncio.Event()
            app.call_later(painted.set)
            await asyncio.wait_for(painted.wait(), 1)
            assert picker.is_mounted and not picker.rows
            release.set()
            await picker.workers.wait_for_complete()
            await pilot.pause()
            assert [row.label() for row in picker.rows] == ["discovered · 9 threads"]
    finally:
        release.set()
