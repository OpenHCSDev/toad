"""Toad starts with no tab open, and while none is the comms sidebar holds the whole window,
carrying what the welcome page did: Toad's banner, the project, the buses and the key hints.
The first tab gives it back its placement, and closing the last tab gives it the window again.
Qt's `sole_sidebar` drive walks the same three states."""

import os
from dataclasses import replace

from agent_comms.messaging.channel_targets import CommandTarget
from agent_comms.messaging.read_basis import NamedViewer
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_model import DeclaredModel
from agent_comms.registry.threads import ExternalThread, NativeThread
from agent_comms.transport.connector_store import HeldUiProfiles
from agent_comms.transport.tailnet_buses import TailnetPeer
from support.agents import peer
from support.roots import Roots
from support.ui import TextualUi

from toad.client.application import BusDiscovery
from toad.client.bus_selection import LocalBus
from toad.constants import ALL_COMMS_TARGET
from toad.launch_binding import AgentAttached
from toad.screens.bus_choice import BusRows
from toad.widgets.channels_sidebar import (
    ChannelsSidebar,
    SidebarBanner,
    SidebarBuses,
    SidebarHeading,
    SidebarHints,
    SidebarLocationNote,
)
from toad.widgets.sidebar_tree import CommsRow

HINT = "n new session"
PARTS = (SidebarBanner, SidebarLocationNote, SidebarBuses, SidebarHints)


def shot(ui: TextualUi, name: str) -> None:
    """Save the frame where TOAD_SHOTS names, for a side-by-side with Qt's drive."""
    folder = os.environ.get("TOAD_SHOTS")
    if folder:
        app, _ = ui.textual
        app.save_screenshot(filename=f"{name}.svg", path=folder)


def parts_shown(sidebar: ChannelsSidebar) -> dict[str, bool]:
    """Whether each part is displayed, its containers up to the sidebar included."""
    def shown(widget) -> bool:
        lineage = [widget, *widget.ancestors]
        return all(node.display for node in lineage[:lineage.index(sidebar)])
    return {part.__name__: shown(sidebar.query_one(part)) for part in PARTS}


def row(sidebar: ChannelsSidebar, name: str) -> CommsRow | None:
    return next((row for row in sidebar.roster.query(CommsRow) if row.target_name == name), None)


async def alone(ui: TextualUi, *names: str) -> ChannelsSidebar:
    """The comms sidebar holds the window with the welcome's parts, listing ``names``."""
    app, _ = ui.textual
    sidebar = app.workspace_chrome.channels
    await ui.until_shows(HINT)
    await ui.until(lambda: sidebar.holds_alone and not sidebar.collapsed
                   and sidebar.region.width == app.screen.size.width
                   and all(row(sidebar, name) is not None for name in (ALL_COMMS_TARGET, *names)),
                   why="the comms sidebar to hold the whole window with its rows")
    assert all(parts_shown(sidebar).values()), parts_shown(sidebar)
    await ui.until(lambda: "██" in ui.painted(sidebar.query_one(SidebarBanner)),
                   why="the banner to be painted at the sidebar's head")
    assert not sidebar.toggle_control.display and not sidebar.resize_handle.display
    return sidebar


async def test_starting_opens_no_tab_and_starts_no_agent(workspace):
    workspace.thread("alpha", "team")
    async with workspace.app(session=False, binding=AgentAttached(peer("echo"))) as ui:
        sidebar = await alone(ui, "alpha")
        assert ui.tabs() == ()
        app, _ = ui.textual
        assert not app.workspace_sessions.source.view.matches_launch(
            peer("echo").identity, "unopened-session"
        )
        assert "Buses" in ui.painted(sidebar.query_one(SidebarBuses))
        assert not workspace.child_processes("echo.py"), "starting Toad started its agent"
        assert not workspace.received()
        assert workspace.project.name not in workspace.comms.registry.snapshot().threads
        shot(ui, "tui-1-alone")


async def test_the_first_tab_gives_the_sidebar_its_placement_and_closing_it_gives_the_window_back(workspace):
    async with workspace.app(session=False) as ui:
        app, _ = ui.textual
        sidebar = await alone(ui)
        await ui.click(ALL_COMMS_TARGET)
        await ui.until(lambda: len(ui.tabs()) == 1 and not sidebar.holds_alone,
                       why="the first tab to open")
        await ui.until(lambda: not any(parts_shown(sidebar).values()),
                       why="the welcome's parts to leave the sidebar")
        assert ui.selected_tab == ui.tabs()[0].identity
        assert not ui.shows(HINT)
        assert sidebar.toggle_control.display
        assert sidebar.region.width < app.screen.size.width
        shot(ui, "tui-2-tab")
        await ui.close_tab(ui.selected_tab)
        await ui.until(lambda: ui.tabs() == (), why="the last tab to close")
        sidebar = await alone(ui)
        banner = sidebar.query_one(SidebarBanner)
        await ui.until(lambda: banner not in app.colours.clock.running.values(),
                       why="the banner's sweep to finish")
        shot(ui, "tui-3-closed")


async def test_opening_a_thread_run_elsewhere_opens_its_history_read_as_the_user(workspace):
    workspace.comms.registry.declare(
        ExternalThread("scribe", frozenset({"team"}), Checkout(workspace.project))
    )
    async with workspace.app(session=False) as ui:
        await alone(ui, "scribe")
        await ui.click("scribe")
        app, _ = ui.textual
        await ui.until(lambda: app.selected_session.thread_identity.thread_name() == "scribe",
                       why="the thread's tab selected")
        assert len(ui.tabs()) == 1
        await ui.write_draft("hello scribe")
        await ui.press("enter")

        def sent_messages():
            return tuple(message for message in workspace.comms.views.history_page(
                CommandTarget.named("scribe"), viewer=NamedViewer(workspace.viewer),
            ).messages if message.body == "hello scribe" and message.target == "scribe")

        await ui.until(sent_messages, why="the message on the wire")
        assert sent_messages()[0].sender == workspace.viewer
        assert not ui.shows(HINT)


async def test_closing_the_last_tab_gives_the_window_back_and_stops_its_agent(workspace):
    async with workspace.app(session=False, binding=AgentAttached(peer("echo"))) as ui:
        await alone(ui)
        await ui.new_session()
        await ui.until(lambda: len(ui.tabs()) == 1, why="the new session's tab")
        await ui.until_agent_ready()
        assert not ui.shows(HINT)
        await ui.close_tab(ui.selected_tab)
        await alone(ui)
        assert ui.tabs() == ()
        await ui.until(lambda: not workspace.child_processes("echo.py"),
                       why="the closed session's agent to be gone")


async def test_going_back_from_the_only_tab_stays_on_it(workspace):
    async with workspace.app(session=False) as ui:
        await alone(ui)
        await ui.click(ALL_COMMS_TARGET)
        await ui.until(lambda: len(ui.tabs()) == 1, why="the channel's tab")
        channel = ui.selected_tab
        await ui.return_to_owner()
        assert ui.selected_tab == channel and not ui.shows(HINT)


async def test_a_launch_that_names_a_session_opens_it(workspace):
    workspace.thread("saved-session", "team")
    async with workspace.app(session=False, resume="saved-session") as ui:
        await ui.until(lambda: len(ui.tabs()) == 1, why="the named session's tab")
        assert ui.selected_tab == ui.tabs()[0].identity
        assert not ui.shows(HINT)


async def test_a_thread_row_tooltip_names_its_model_by_text(workspace):
    thread = NativeThread("alpha", frozenset({"team"}), Checkout(workspace.project))
    workspace.comms.registry.declare(replace(thread, model=DeclaredModel("openai-codex/gpt-6.1-sol")))
    async with workspace.app(session=False) as ui:
        sidebar = await alone(ui, "alpha")
        assert "openai-codex/gpt-6.1-sol" in str(row(sidebar, "alpha").tooltip).splitlines()


async def test_the_sidebar_lists_the_tailnets_buses_and_asks_once_per_window(
        workspace, monkeypatch, tmp_path):
    """Tristan: "I would like it to show the buses as well so that it would list out the
    buses that are available", then "It also didn't list the other buses on the tailnet".

    The section inherits the Open-bus dialog's own listing: this machine's own bus at once,
    then the peers the window's one ask of the tailnet found. The sidebar holds the window
    whenever no tab is open, so listing them again shows that answer instead of sweeping."""

    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    tailnet = Roots.of_this_process().tailnet
    tailnet.hold(TailnetPeer("desktop", "100.124.133.120", True), 247)
    tailnet.held.touch()

    async with workspace.app(session=False) as ui:
        app, _ = ui.textual
        sidebar = await alone(ui)
        buses = sidebar.query_one(SidebarBuses)
        # This machine's own bus is listed without asking anyone, so the section is never
        # an empty box while the tailnet is still answering.
        assert [type(row).__name__ for row in buses.rows] == ["LocalBus"]
        assert "Buses" in ui.painted(buses.query_one(SidebarHeading))
        assert LocalBus().label() in ui.painted(buses.query_one(BusRows))

        tailnet.held.unlink()
        await ui.until(lambda: len(buses.rows) == 2, why="the window's ask to answer")
        assert buses.rows[-1].label() == "desktop · 247 threads"
        assert "desktop · 247 threads" in ui.painted(buses.query_one(BusRows))

        # Listed again, the buses are what the window found, and nobody is asked.
        tailnet.hold(TailnetPeer("laptop", "100.64.0.7", True), 62)
        again = SidebarBuses()
        await sidebar.content_stack.mount(again)
        assert [row.label() for row in again.rows] == ["This machine", "desktop · 247 threads"]
        for _ in range(6):
            await ui.step()
        assert not any(worker.group == BusDiscovery.group and not worker.is_finished
                       for worker in app.workers), "listing the buses again starts no sweep"
        assert len(again.rows) == 2


async def test_the_banner_sweeps_only_while_the_sidebar_holds_a_focused_window(workspace):
    async with workspace.app(session=False) as ui:
        app, _ = ui.textual
        sidebar = await alone(ui)
        banner, clock = sidebar.query_one(SidebarBanner), app.colours.clock
        await ui.until(lambda: banner.played in banner.effects, why="the banner's sweep to start")
        animation = banner.effects[banner.played].animation
        assert clock.running.get(animation) is banner and animation.effect is banner.played

        session = await ui.new_session()
        await ui.until(lambda: not sidebar.holds_alone, why="the first tab")
        await ui.step()
        assert banner.played not in banner.effects and banner not in clock.running.values()

        built = banner.played
        await ui.close_tab(session)
        await ui.until(lambda: banner.played in banner.effects, why="the banner's sweep to play again")
        assert banner.played is built, "the frames were built again for the same colour scheme"

        app.app_focus = False
        await ui.step()
        assert banner.played not in banner.effects and banner not in clock.running.values()


async def test_a_finished_sweep_leaves_the_clock(workspace):
    async with workspace.app(session=False) as ui:
        app, _ = ui.textual
        banner = (await alone(ui)).query_one(SidebarBanner)
        await ui.until(lambda: banner.played in banner.effects, why="the banner's sweep to start")
        await ui.until(lambda: banner not in app.colours.clock.running.values(), why="the sweep to finish")
        assert banner.render() == app.colours.paint_text(banner.played.final, None)
