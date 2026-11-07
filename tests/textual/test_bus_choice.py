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
        app.open_bus(choice)

        async def ended() -> None:
            while not isinstance(app.return_value, Reconnected):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(ended(), 30)
    assert app.return_value == Reconnected(LaunchRuntime.running(), choice)


async def test_a_dismissed_picker_changes_nothing(workspace):
    """Through the fixture that owns a running app: the earlier hand-built ToadApp here was
    the only test that let one close on its own, and it died in application start."""
    async with workspace.app(size=(140, 48)) as ui:
        ui.app.open_bus(None)
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
        app.push_screen(BusChoices.offered(), app.open_bus)
        await ui.until(lambda: isinstance(app.screen, BusChoices), why="the picker")
        for _ in range(4):
            await ui.step()
        assert isinstance(app.screen, BusChoices), "the picker stays up until a row is chosen"
        assert not isinstance(app.return_value, Reconnected), "nothing is opened by showing a list"
