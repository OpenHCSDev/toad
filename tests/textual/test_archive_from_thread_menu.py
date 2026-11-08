"""Textual-facing: the sidebar's thread menu (a ContextMenu) lists every declared thread command, and
choosing Archive archives the thread on the wire while keeping its messages, goal history, session file
and saved session."""

import json
from datetime import UTC, datetime
from importlib import import_module

from agent_comms import cli_verbs
from agent_comms.native_entries import SessionEntry
from agent_comms.projects.checkouts import Checkout
from agent_comms.messaging.channel_targets import CommandTarget
from agent_comms.messaging.read_basis import NamedViewer
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.cli_command import CliCommand
from agent_comms.cli_verbs.archive import ArchiveCliCommand
from agent_comms.planning.goal_actions import SetGoalAction
from agent_comms.thread_status import ArchivedThreadStatus, StoppedThreadStatus
from agent_comms.registry.threads import NativeThread
from textual.geometry import Offset

from toad.db import DB
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar
from agent_comms.nominal.field_codec import AcpSessionId


async def test_a_newly_declared_archive_command_runs_from_the_menu_and_keeps_history(workspace, tmp_path, monkeypatch):
    # A declared verb is a module in the verbs package (ModuleMembers), so the new one is a new file.
    (tmp_path / "retain_action.py").write_text(
        '"""Retain the thread."""\n'
        "from agent_comms.cli_verbs.archive import ArchiveCliCommand\n"
        "class RetainAction(ArchiveCliCommand):\n"
        '    """A command declared here must appear in the menu and run with no other edit."""\n'
    )
    monkeypatch.setattr(cli_verbs, "__path__", [*cli_verbs.__path__, str(tmp_path)])
    RetainAction = import_module("agent_comms.cli_verbs.retain_action").RetainAction

    commands = CliCommand.members_with(CliCommand)
    assert RetainAction in commands
    assert len({command.declared_name for command in commands}) == len(commands)
    assert all(command.help for command in commands)

    project, comms = workspace.project, workspace.comms
    session_file = project / "peer.jsonl"
    session_file.write_text(json.dumps(SessionEntry.fresh(project, datetime.now(UTC)).to_wire()) + "\n")
    comms.registry.register(NativeThread("owner", frozenset(), Checkout(project)))
    comms.registry.register(NativeThread("peer", frozenset(), Checkout(project), session_file=RegistrySessionLocation.from_path(session_file, workspace.comms.root)),
                            StoppedThreadStatus())
    comms.messaging.send("peer", "owner", "Retain this archived conversation")
    comms.goals.update_goal("peer", SetGoalAction(text="Retain the goal revisions"))
    def peer_messages():
        return comms.views.history_page(CommandTarget.named("owner"), viewer=NamedViewer("peer")).messages

    messages = peer_messages()
    assert [message.body for message in messages] == ["Retain this archived conversation"]
    goals = comms.goals.goal_history("peer")
    thread = comms.registry.require("peer")
    saved_bytes = session_file.read_bytes()
    async with workspace.app(size=(110, 38)) as ui:
        app, _ = ui.textual
        await app.selected_session.on_coordination_update(comms.configuration.answer("owner"))
        db = DB()
        await db.create()
        saved = await db.session_new("peer", "Comms", "agent-comms.openhcs.dev", AcpSessionId("peer"))
        assert saved is not None
        sidebar = app.screen.query_one(CommsSidebar)

        def peer_row():
            return next((row for row in sidebar.query(CommsRow) if row.target_name == "peer"), None)

        await ui.until(lambda: sidebar.navigation.ready.is_set() and peer_row() is not None, why="the peer's sidebar row")
        peer_row().show_menu(sidebar, Offset(5, 5))
        actions = await ui.menu("the thread menu and its commands")
        assert ArchiveCliCommand.declared_name in actions
        assert "comms_delete" not in actions
        await ui.choose_menu_action(RetainAction.declared_name)
        await ui.until(lambda: comms.registry.status("peer") == ArchivedThreadStatus(), why="the thread archived")
        await ui.until(lambda: "peer" not in app.thread_actions.pending, why="the command to finish")
        assert comms.registry.require("peer").incarnation == thread.incarnation
        assert peer_messages() == messages
        assert comms.goals.goal_history("peer") == goals
        assert session_file.read_bytes() == saved_bytes
        assert await db.session_get(saved) is not None
