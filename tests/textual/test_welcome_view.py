"""Toad starts with no tab open and shows the welcome view until one is opened."""
from agent_comms.repo import Checkout
from toad.session_scope import AgentAttached

from support.agents import peer
from support.ui import TextualUi
from agent_comms.channel_targets import CommandTarget
from agent_comms.read_basis import NamedViewer
from agent_comms.threads import NativeThread
from toad.constants import ALL_COMMS_TARGET
from toad.screens.welcome import WelcomeChannels, WelcomeEntries, WelcomeScreen, WelcomeThreads
from toad.widgets.comms_sidebar import CommsRow

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
    entries = row.query_ancestor(WelcomeEntries)
    for _ in range(len(entries.rows) + 1):
        if app.focused is row:
            return
        await ui.press("down")
    raise AssertionError(f"welcome row {row.target_name!r} is unreachable:\n{ui.visible_text()}")


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
    from agent_comms.threads import ExternalThread

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
        await ui.until(lambda: len(ui.tabs()) == 1, why="the thread's tab")
        app, _ = ui.textual
        assert app.selected_session.thread_identity.thread_name() == "scribe"
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
    from dataclasses import replace

    from agent_comms.thread_model import DeclaredModel

    thread = NativeThread("alpha", frozenset({"team"}), Checkout(workspace.project))
    workspace.comms.registry.declare(replace(thread, model=DeclaredModel("openai-codex/gpt-6.1-sol")))
    async with workspace.app(session=False) as ui:
        entries = await welcome_entries(ui, "alpha")
        row = entries.query_one(WelcomeThreads).rows["alpha"]
        assert "openai-codex/gpt-6.1-sol" in str(row.tooltip).splitlines()
