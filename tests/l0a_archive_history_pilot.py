"""Installed Toad menu archives a real isolated thread and retains its history."""
from runtime_fixture import coordination_update

from toad.thread_actions import ArchiveAction, ThreadAction
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import wire
from agent_comms.goal_actions import SetGoalAction
from agent_comms.thread_status import ArchivedThreadStatus, StoppedThreadStatus
from agent_comms.threads import Thread
from comms_boundary_fixture import coordination_fact
from textual.geometry import Offset

from toad.app import ToadApp
from toad.db import DB
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_sidebar import CommsSidebar


async def until(pilot, predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await pilot.pause(0.02)


async def main():
    class RetainAction(ArchiveAction):
        """One new declaration must appear and run through the mounted menu."""

    menu = ThreadAction.menu()
    assert RetainAction in menu
    assert len({action.declared_name for action in menu}) == len(menu)
    for action in menu:
        assert action.menu_label() and action.pending

    artifacts = Path(__file__).resolve().parents[1] / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="l0a-archive-", dir=artifacts) as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        transcript = root / "peer.jsonl"
        transcript.write_text('{"type":"session","id":"retained"}\n')
        comms.registry.register(Thread("owner", frozenset(), str(root)))
        comms.registry.register(
            Thread("peer", frozenset(), str(root), session_file=str(transcript)),
            StoppedThreadStatus(),
        )
        comms.messaging.send("peer", "owner", "Retain this archived conversation")
        comms.goals.update_goal("peer", SetGoalAction(text="Retain the goal revisions"))
        before_messages = comms.views.full_history()
        before_goals = comms.goals.goal_history("peer")
        before_thread = comms.registry.require("peer")
        before_transcript = transcript.read_bytes()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            app.theme = "textual-dark"
            await pilot.pause()
            await app.screen.on_coordination_update(coordination_update(str(comms.root), 'owner'))
            db = DB()
            assert await db.create()
            saved = await db.session_new(
                "peer", "Comms", "agent-comms.openhcs.dev", "peer"
            )
            assert saved is not None
            sidebar = app.screen.query_one(CommsSidebar)
            await until(pilot, lambda: sidebar.navigation_ready.is_set())
            sidebar._show_thread_menu("peer", Offset(5, 5))
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            actions = [item.action for item in app.screen.query(ContextMenuItem)]
            assert ArchiveAction.declared_name in actions
            assert "comms_delete" not in actions
            archive = next(item for item in app.screen.query(ContextMenuItem)
                           if item.action == RetainAction.declared_name)
            assert await pilot.click(archive)
            await until(
                pilot, lambda: comms.registry.status("peer") == ArchivedThreadStatus()
            )
            await until(pilot, lambda: "peer" not in app.pending_thread_actions)
            assert (
                comms.registry.require("peer").incarnation == before_thread.incarnation
            )
            assert comms.views.full_history() == before_messages
            assert comms.goals.goal_history("peer") == before_goals
            assert transcript.read_bytes() == before_transcript
            assert await db.session_get(saved) is not None
            assert app._exception is None
    print(
        "archive UI: real declared menu archives; messages, goal revisions, identity, transcript and saved session retained"
    )


if __name__ == "__main__":
    asyncio.run(main())
