"""Slow owner/history and sidebar reads must not hold navigation or draft input."""

import asyncio
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from agent_comms import Thread, TranscriptCursor, TranscriptEvent, TranscriptPage, wire
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.acp.messages import TranscriptSnapshot
from toad.agent import AgentReady
from toad.widgets.conversation import ThreadLoading
from toad.widgets.comms_sidebar import CommsSidebar


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-async-open-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.register(Thread("slow-thread", frozenset(), str(root), pid=os.getpid()))
        release = asyncio.Event()
        started = asyncio.Event()
        disk_release = threading.Event()
        agent_data = {"name": "Slow test owner", "identity": "slow-test", "short_name": "slow",
                      "run_command": {"*": "/bin/false"}, "protocol": "acp"}

        async def start(agent, target):
            agent._message_target = target

            async def attach():
                started.set()
                await release.wait()
                cursor = TranscriptCursor("test", 0)
                page = TranscriptPage((TranscriptEvent("assistant", "LOADED-HISTORY-END"),),
                                      cursor, cursor, False, False)
                target.post_message(TranscriptSnapshot(page.events, page))
                target.post_message(AgentReady())

            agent._task = asyncio.create_task(attach())

        app = ToadApp(project_dir=str(root))
        try:
            async with app.run_test(size=(110, 34)) as pilot:
                await pilot.pause()
                source = app.current_mode
                app.screen._agent = agent_data
                sidebar = app.screen.query_one(CommsSidebar)
                await sidebar.sync_sessions()
                original_read = type(comms).viewer_snapshot

                def slow_read(self, *args, **kwargs):
                    if not disk_release.wait(8):
                        raise TimeoutError("Test disk gate was not released")
                    return original_read(self, *args, **kwargs)

                with patch.object(Agent, "start", start), patch.object(type(comms), "viewer_snapshot", slow_read):
                    mode = await asyncio.wait_for(app.open_thread_session(
                        owner_mode=source, project_path=root, target="slow-thread"), 2)
                    await asyncio.wait_for(started.wait(), 2)
                    await pilot.pause()
                    frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                    assert "Loading new thread and history" in frame, frame
                    conversation = app.screen.conversation
                    loading = conversation.query_one(ThreadLoading)
                    viewport = conversation.window.content_region
                    assert loading.region.width >= viewport.width - 2
                    assert loading.region.height >= viewport.height - 2
                    assert abs(loading.region.center[1] - viewport.center[1]) <= 3
                    caption = "Loading new thread and history…"
                    painted_line = next(line for line in frame.splitlines() if caption in line)
                    caption_center = painted_line.index(caption) + len(caption) // 2
                    assert abs(caption_center - viewport.center[0]) <= 2, (
                        caption_center, viewport.center[0], painted_line)
                    ring = loading.render().plain.splitlines()
                    ring_rows = [line for line in ring if any(mark in line for mark in "●•·")]
                    ring_columns = [index for line in ring_rows for index, char in enumerate(line)
                                    if char in "●•·"]
                    assert max(ring_columns) - min(ring_columns) + 1 <= len(ring_rows) * 1.5
                    large_rows = loading.render().plain.count("\n")
                    assert large_rows >= 6
                    await pilot.resize_terminal(78, 28)
                    await pilot.pause()
                    assert loading.region.width >= conversation.window.content_region.width - 2
                    assert loading.render().plain.count("\n") < large_rows
                    await pilot.resize_terminal(110, 34)
                    await pilot.pause()
                    conversation.prompt.focus()
                    await pilot.press("h", "i")
                    assert conversation.prompt.text == "hi"
                    await asyncio.wait_for(app.switch_mode(source), 2)
                    await asyncio.wait_for(app.switch_mode(mode), 2)
                    assert not release.is_set() and not disk_release.is_set()
                    assert conversation.query(ThreadLoading)
                    release.set()
                    disk_release.set()
                    async with asyncio.timeout(5):
                        while not conversation.agent_ready:
                            await asyncio.sleep(.02)
                    await pilot.pause()
                    assert not conversation.query(ThreadLoading)
                    assert conversation.prompt.text == "hi"
                    frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                    assert "LOADED-HISTORY-END" in frame
        finally:
            release.set()
            disk_release.set()
    print("async thread open: spinner, typing, and tab switching work before owner and disk reads complete")


if __name__ == "__main__":
    asyncio.run(main())
