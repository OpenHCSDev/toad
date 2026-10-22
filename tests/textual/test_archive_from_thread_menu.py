"""Textual-facing: the sidebar's thread menu (a ContextMenu) lists every declared thread command, and
choosing Archive archives the thread on the wire while keeping its messages, goal history, session file
and saved session."""

from agent_comms.cli_commands import ArchiveCliCommand, CliCommand
from agent_comms.goal_actions import SetGoalAction
from agent_comms.thread_status import ArchivedThreadStatus, StoppedThreadStatus
from textual.geometry import Offset

from toad.db import DB
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar


async def test_a_newly_declared_archive_command_runs_from_the_menu_and_keeps_history(workspace):
    class RetainAction(ArchiveCliCommand):
        """A command declared here must appear in the menu and run with no other edit."""

    commands = CliCommand.members_with(CliCommand)
    assert RetainAction in commands
    assert len({command.declared_name for command in commands}) == len(commands)
    assert all(command.help for command in commands)

    project, comms = workspace.project, workspace.comms
    session_file = project / "peer.jsonl"
    session_file.write_text('{"type":"session","id":"retained"}\n')
    comms.registry.register(comms.registry.new_thread("owner", frozenset(), str(project)))
    comms.registry.register(comms.registry.new_thread("peer", frozenset(), str(project), session_file=str(session_file)),
                            StoppedThreadStatus())
    comms.messaging.send("peer", "owner", "Retain this archived conversation")
    comms.goals.update_goal("peer", SetGoalAction(text="Retain the goal revisions"))
    messages = comms.views.full_history()
    goals = comms.goals.goal_history("peer")
    thread = comms.registry.require("peer")
    saved_bytes = session_file.read_bytes()
    async with workspace.app(size=(110, 38)) as ui:
        app, pilot = ui.textual
        await app.selected_session.on_coordination_update(comms.configuration.answer("owner"))
        db = DB()
        await db.create()
        saved = await db.session_new("peer", "Comms", "agent-comms.openhcs.dev", "peer")
        assert saved is not None
        sidebar = app.screen.query_one(CommsSidebar)

        def peer_row():
            return next((row for row in sidebar.query(CommsRow) if row.target_name == "peer"), None)

        await ui.until(lambda: sidebar.navigation.ready.is_set() and peer_row() is not None, why="the peer's sidebar row")
        peer_row().show_menu(sidebar, Offset(5, 5))
        await ui.until(lambda: isinstance(app.screen, ContextMenu) and bool(app.screen.query(ContextMenuItem)),
                       why="the thread menu and its commands")
        actions = [item.action for item in app.screen.query(ContextMenuItem)]
        assert ArchiveCliCommand.declared_name in actions
        assert "comms_delete" not in actions
        archive = next(item for item in app.screen.query(ContextMenuItem)
                       if item.action == RetainAction.declared_name)
        assert await pilot.click(archive)
        await ui.until(lambda: comms.registry.status("peer") == ArchivedThreadStatus(), why="the thread archived")
        await ui.until(lambda: "peer" not in app.thread_actions.pending, why="the command to finish")
        assert comms.registry.require("peer").incarnation == thread.incarnation
        assert comms.views.full_history() == messages
        assert comms.goals.goal_history("peer") == goals
        assert session_file.read_bytes() == saved_bytes
        assert await db.session_get(saved) is not None
