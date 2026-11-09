"""Toad starts with no tab open and shows the welcome view until one is opened."""

from dataclasses import replace

from agent_comms.messaging.channel_targets import CommandTarget
from agent_comms.messaging.read_basis import NamedViewer
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_model import DeclaredModel
from agent_comms.registry.threads import ExternalThread, NativeThread
from agent_comms.transport.connector_store import HeldUiProfiles
from agent_comms.transport.tailnet_buses import TailnetBuses
from support.agents import peer
from support.ui import TextualUi

from toad.bus_selection import LocalBus
from toad.constants import ALL_COMMS_TARGET
from toad.launch_binding import AgentAttached
from toad.screens.bus_choice import BusRows
from toad.screens.welcome import (
    WelcomeBuses,
    WelcomeChannels,
    WelcomeEntries,
    WelcomeHeading,
    WelcomeScreen,
    WelcomeThreads,
)
from toad.widgets.sidebar_tree import CommsRow

HINT = "n new session"


async def welcome_entries(ui: TextualUi, *threads: str) -> WelcomeEntries:
    """Wait for the welcome view's own published rows, not matching sidebar text."""
    app, _ = ui.textual
    await ui.until_shows(HINT)
    entries = app.screen.query_one(WelcomeEntries)
    channels = entries.query_one(WelcomeChannels)
    listed_threads = entries.query_one(WelcomeThreads)
    await ui.until(
        lambda: entries.query_ancestor(WelcomeScreen).is_current
        and entries.is_on_screen
        and entries.model_state.shows_model()
        and ALL_COMMS_TARGET in channels.rows
        and channels.rows[ALL_COMMS_TARGET].is_on_screen
        and all(name in listed_threads.rows and listed_threads.rows[name].is_on_screen
                for name in threads),
        why="the welcome channel and requested thread rows to be shown",
    )
    assert ui.shows(HINT)
    assert WelcomeChannels.TITLE in ui.painted(channels.row)
    assert ALL_COMMS_TARGET in ui.painted(channels.rows[ALL_COMMS_TARGET])
    if threads:
        assert WelcomeThreads.TITLE in ui.painted(listed_threads.row)
    return entries


async def focus_row(ui: TextualUi, row: CommsRow) -> None:
    """Reach this welcome row with keys, preserving the real navigation path."""
    app, _ = ui.textual

    # Rows mount a step per frame, so the list can still grow while the cursor walks it.
    async def reached() -> bool:
        if app.focused is row:
            return True
        await ui.press("down")
        return False

    await ui.until(reached, why=f"welcome row {row.target_name!r} reached with Down")


async def test_starting_opens_no_tab_and_starts_no_agent(workspace):
    workspace.thread("alpha", "team")
    async with workspace.app(session=False, binding=AgentAttached(peer("echo"))) as ui:
        await welcome_entries(ui, "alpha")
        assert ui.tabs() == ()
        app, _ = ui.textual
        assert not app.workspace_sessions.source.view.matches_launch(
            peer("echo").identity, "unopened-session"
        )
        assert ui.shows(HINT)
        assert not workspace.child_processes(
            "echo.py"
        ), "starting Toad started its agent"
        assert not workspace.received()
        assert workspace.project.name not in workspace.comms.registry.snapshot().threads


async def test_opening_a_channel_opens_its_tab_in_place_of_the_view(workspace):
    workspace.thread("alpha", "team")
    async with workspace.app(session=False) as ui:
        entries = await welcome_entries(ui, "alpha")
        await focus_row(ui, entries.query_one(WelcomeChannels).rows[ALL_COMMS_TARGET])
        await ui.press("enter")
        await ui.until(lambda: len(ui.tabs()) == 1, why="the channel's tab")
        assert ui.selected_tab == ui.tabs()[0].identity
        assert not ui.shows(HINT)


async def test_opening_a_thread_run_elsewhere_opens_its_history_read_as_the_user(
    workspace,
):

    workspace.comms.registry.declare(
        ExternalThread(
            "scribe",
            frozenset({"team"}),
            Checkout(workspace.project))
    )
    async with workspace.app(session=False) as ui:
        entries = await welcome_entries(ui, "scribe")
        await focus_row(ui, entries.query_one(WelcomeThreads).rows["scribe"])
        await ui.press("enter")
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


async def test_closing_the_last_tab_shows_the_view_again_and_starts_no_agent(workspace):
    async with workspace.app(session=False, binding=AgentAttached(peer("echo"))) as ui:
        await welcome_entries(ui)
        await ui.new_session()
        await ui.until(lambda: len(ui.tabs()) == 1, why="the new session's tab")
        await ui.until_agent_ready()
        assert not ui.shows(HINT)
        await ui.close_tab(ui.selected_tab)
        await welcome_entries(ui)
        assert ui.tabs() == ()
        await ui.until(
            lambda: not workspace.child_processes("echo.py"),
            why="the closed session's agent to be gone",
        )


async def test_going_back_from_the_only_tab_stays_on_it(workspace):
    async with workspace.app(session=False) as ui:
        entries = await welcome_entries(ui)
        await focus_row(ui, entries.query_one(WelcomeChannels).rows[ALL_COMMS_TARGET])
        await ui.press("enter")
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
        entries = await welcome_entries(ui, "alpha")
        row = entries.query_one(WelcomeThreads).rows["alpha"]
        assert "openai-codex/gpt-6.1-sol" in str(row.tooltip).splitlines()


async def test_the_splash_lists_the_buses_this_machine_can_open(workspace, monkeypatch, tmp_path):
    """Tristan: "I would like it to show the buses as well so that it would list out the
    buses that are available".

    The section inherits the Open-bus dialog's own listing, so what it shows and what
    choosing a row does are the dialog's; this holds that the splash really lists them and
    that a found peer arrives in the same row set.
    """

    monkeypatch.setattr(HeldUiProfiles, "directory", classmethod(lambda cls: tmp_path))
    def no_discovery_from_the_splash(cls):
        raise AssertionError("the splash must not sweep the tailnet to list buses")

    monkeypatch.setattr(TailnetBuses, "seen", classmethod(no_discovery_from_the_splash))

    # session=False, like every other splash case here: the splash is what shows when no
    # tab is open, and workspace.app() opens one.
    async with workspace.app(session=False) as ui:
        entries = await welcome_entries(ui)
        buses = entries.query_one(WelcomeBuses)
        # This machine's own bus is listed without asking anyone, so the section is never
        # an empty box while the tailnet is still answering.
        assert [type(row).__name__ for row in buses.rows] == ["LocalBus"]
        assert "Buses" in ui.painted(buses.query_one(WelcomeHeading))
        assert LocalBus().label() in ui.painted(buses.query_one(BusRows))
        # And it does NOT sweep the tailnet to show this. The splash appears whenever
        # there are no tabs open, so discovering here would be seconds of ssh to every
        # peer on every launch, for a list nobody asked to see. The dialog asks; this
        # lists what the machine already holds.
        for _ in range(6):
            await ui.step()
        assert [type(row).__name__ for row in buses.rows] == ["LocalBus"], (
            "the splash lists held buses and starts no discovery")
        assert not any(worker.group == "bus-discovery" for worker in buses.workers)
