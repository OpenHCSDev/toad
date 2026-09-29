"""Click a pre-persistence fork row, then scroll inherited history after persistence."""
from agent_comms.acp_extension import TranscriptSnapshotUpdate
from toad.acp.messages import CommsUpdated

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.comms import wire
from agent_comms.threads import Thread
from comms_boundary_fixture import attach_coordination, snapshot_fact
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.agent import AgentReady
from toad.screens.main import MainScreen
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-fresh-fork-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        session = root / "parent.jsonl"
        session.write_text(
            "".join(
                (
                    json.dumps(
                        {
                            "type": "message",
                            "message": {
                                "role": "assistant",
                                "content": f"Inherited record {i}",
                            },
                        }
                    )
                    + "\n"
                    for i in range(60)
                )
            )
        )
        comms = wire(root / "wire")
        comms.registry.declare(
            Thread("parent", frozenset(), str(root), session_file=str(session))
        )
        comms.registry.declare(
            Thread(
                "child",
                frozenset(),
                str(root),
                parent="parent",
                task="FORK-TASK-MARKER",
            )
        )
        started = asyncio.Event()

        async def start(agent, target):
            agent.attach_surface(target)
            attach_coordination(agent, str(root / "wire"), "child")
            page = await agent.get_transcript_page()
            target.post_message(CommsUpdated(TranscriptSnapshotUpdate(page)))
            target.post_message(AgentReady())
            started.set()

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(115, 34)) as pilot:
            await pilot.pause()
            app.screen._agent = {
                "name": "Test owner",
                "identity": "test",
                "short_name": "test",
                "run_command": {"*": "/bin/false"},
                "protocol": "acp",
            }
            app.screen._comms_thread = "parent"
            app.screen.initial_coordination_root = str(root / "wire")
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.observation.sync()
            row = next(row for row in sidebar.query(CommsRow) if row.target_name == "child")
            # Registry reservation becomes a live owner before its session file
            # exists. Refresh must update even an already-created sidebar row.
            comms.owners.acquire_thread("child", owner_pid=os.getpid())
            await sidebar.observation.sync()
            with patch.object(Agent, "start", start):
                await pilot.click(row)
                await asyncio.wait_for(started.wait(), 4)
                await pilot.pause()
                assert (
                    isinstance(app.screen, MainScreen)
                    and app.screen._session_thread == "child"
                )
                assert all(tab.title != "@child" for tab in app.open_tabs)
                view = app.selected_session.conversation
                history = view.query_one(TranscriptHistory)
                frame = "\n".join(
                    (strip.text for strip in app.screen._compositor.render_strips())
                )
                assert "FORK-TASK-MARKER" in frame and history.has_older, frame
                own = root / "child.jsonl"
                own.write_text(
                    json.dumps(
                        {
                            "type": "message",
                            "message": {
                                "role": "assistant",
                                "content": "CHILD-OWN-REPLY",
                            },
                        }
                    )
                    + "\n"
                )
                comms.threads.attach_session("child", str(own), pid=os.getpid())
                assert (
                    comms.transcripts.thread_transcript_page("child").events[0].text
                    == "CHILD-OWN-REPLY"
                )
                async with asyncio.timeout(10):
                    while history.has_older:
                        view.window.scroll_home(animate=False, immediate=True)
                        await pilot.pause(0.05)
                view.window.scroll_home(animate=False, immediate=True)
                await pilot.pause()
                frame = "\n".join(
                    (strip.text for strip in app.screen._compositor.render_strips())
                )
                assert "Inherited record 0" in frame, frame
    print(
        "fresh fork: real row click opens full thread, task visible, inherited history scrolls after persistence"
    )


if __name__ == "__main__":
    asyncio.run(main())
