"""Toad starts with no tab open and shows the welcome view until one is opened."""
from toad.session_scope import AgentAttached

from support.agents import peer
from agent_comms.channel_targets import CommandTarget
from agent_comms.read_basis import NamedViewer
from agent_comms.threads import Thread

HINT = "n new session"
# The view's own lists (the sidebar's panel is headed differently).
CHANNELS, THREADS = "▾ Channels", "▾ Threads"


async def focus_row(ui, kind: str) -> None:
    """Move down the welcome view's list to its first row of `kind`."""
    for _ in range(12):
        if ui.focused() == kind:
            return
        await ui.press("down")
    raise AssertionError(f"no {kind} in the welcome view:\n{ui.visible_text()}")


async def test_starting_opens_no_tab_and_starts_no_agent(workspace):
    workspace.thread("alpha", "team")
    async with workspace.app(session=False, binding=AgentAttached(peer("echo"))) as ui:
        await ui.until_shows(THREADS)
        assert ui.tabs() == ()
        app, _ = ui.textual
        assert not app.workspace_sessions.source.view.matches_launch(
            peer("echo").identity, "unopened-session"
        )
        assert ui.shows(HINT) and ui.shows(CHANNELS)
        assert not workspace.child_processes(
            "echo.py"
        ), "starting Toad started its agent"
        assert not workspace.received()
        assert workspace.project.name not in workspace.comms.registry.snapshot().threads


async def test_opening_a_channel_opens_its_tab_in_place_of_the_view(workspace):
    workspace.thread("alpha", "team")
    async with workspace.app(session=False) as ui:
        await ui.until_shows(THREADS)
        await focus_row(ui, "CommsRow")
        await ui.press("enter")
        await ui.until(lambda: len(ui.tabs()) == 1, why="the channel's tab")
        assert ui.selected_tab == ui.tabs()[0].identity
        assert not ui.shows(HINT)


async def test_opening_a_thread_run_elsewhere_opens_its_history_read_as_the_user(
    workspace,
):
    from agent_comms.thread_execution import ExternalThreadExecution

    workspace.comms.registry.declare(
        Thread(
            "scribe",
            frozenset({"team"}),
            str(workspace.project),
            execution=ExternalThreadExecution,
        )
    )
    async with workspace.app(session=False) as ui:
        await ui.until_shows(THREADS)
        await focus_row(ui, "ThreadStatusRow")
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
        await ui.until_shows(HINT)
        await ui.new_session()
        await ui.until(lambda: len(ui.tabs()) == 1, why="the new session's tab")
        await ui.until_agent_ready()
        assert not ui.shows(HINT)
        await ui.close_tab(ui.selected_tab)
        await ui.until_shows(HINT)
        assert ui.tabs() == ()
        await ui.until(
            lambda: not workspace.child_processes("echo.py"),
            why="the closed session's agent to be gone",
        )


async def test_going_back_from_the_only_tab_stays_on_it(workspace):
    async with workspace.app(session=False) as ui:
        await ui.until_shows(CHANNELS)
        await focus_row(ui, "CommsRow")
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
