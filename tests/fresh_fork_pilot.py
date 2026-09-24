"""Click a pre-persistence fork row, then scroll inherited history after persistence."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.acp.messages import TranscriptSnapshot
from toad.agent import AgentReady
from toad.screens.main import MainScreen
from toad.widgets.comms_sidebar import CommsSidebar, CommsRow
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-fresh-fork-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        session = root / "parent.jsonl"
        session.write_text("".join(json.dumps({"type": "message", "message": {
            "role": "assistant", "content": f"Inherited record {i}"}}) + "\n" for i in range(60)))
        comms = wire(root / "wire")
        comms.register(Thread("parent", frozenset(), str(root), session_file=str(session)))
        comms.register(Thread("child", frozenset(), str(root), parent="parent", task="FORK-TASK-MARKER"))
        started = asyncio.Event()

        async def start(agent, target):
            agent._message_target = target
            agent._coordination_root = str(root / "wire")
            agent._coordination_thread = "child"
            page = await agent.get_transcript_page()
            target.post_message(TranscriptSnapshot(page.events, page))
            target.post_message(AgentReady())
            started.set()

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(115, 34)) as pilot:
            await pilot.pause()
            app.screen._agent = {"name": "Test owner", "identity": "test", "short_name": "test",
                                 "run_command": {"*": "/bin/false"}, "protocol": "acp"}
            app.screen._comms_thread = "parent"
            app.screen._coordination_root = str(root / "wire")
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.sync_sessions()
            row = next(row for row in sidebar.query(CommsRow) if row.target_name == "child")
            assert row.kind == "dm"
            # Registry reservation becomes a live owner before its session file
            # exists. Refresh must update even an already-created sidebar row.
            comms.acquire_thread("child", owner_pid=os.getpid())
            await sidebar.sync_sessions()
            with patch.object(Agent, "start", start):
                await pilot.click(row)
                await asyncio.wait_for(started.wait(), 4)
                await pilot.pause()
                assert isinstance(app.screen, MainScreen) and app.screen._session_thread == "child"
                assert not any(key.kind == "dm" and key.target == "child" for key in app._comms_modes)
                view = app.screen.conversation
                history = view.query_one(TranscriptHistory)
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "FORK-TASK-MARKER" in frame and history.has_older, frame
                # Persist the child's file after mounting its inherited window.
                # Old ancestor cursors must still reach the beginning, without
                # reading a file supplied by an untrusted arbitrary cursor.
                own = root / "child.jsonl"
                own.write_text(json.dumps({"type": "message", "message": {
                    "role": "assistant", "content": "CHILD-OWN-REPLY"}}) + "\n")
                comms.attach_session("child", str(own), pid=os.getpid())
                assert comms.thread_transcript_page("child").events[0].text == "CHILD-OWN-REPLY"
                async with asyncio.timeout(10):
                    while history.has_older:
                        view.window.scroll_home(animate=False, immediate=True)
                        await pilot.pause(.05)
                view.window.scroll_home(animate=False, immediate=True)
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "Inherited record 0" in frame, frame
    print("fresh fork: real row click opens full thread, task visible, inherited history scrolls after persistence")


if __name__ == "__main__":
    asyncio.run(main())
