"""Slow owner/history and sidebar reads must not hold navigation or draft input."""
from agent_comms.acp_extension import TranscriptSnapshotUpdate
from toad.acp.messages import CommsUpdated

import asyncio
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import wire
from agent_comms.threads import Thread
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from comms_boundary_fixture import snapshot_fact
from runtime_fixture import ToadApp

from toad.acp.agent import Agent
from toad.agent import AgentReady
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.conversation import ThreadLoading


@asynccontextmanager
async def release_on_exit(release, disk_release):
    try:
        yield
    finally:
        release.set()
        disk_release.set()


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-async-open-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        comms.registry.declare(
            Thread(
                "slow-thread",
                frozenset(),
                str(root),
                process_identity=ProcessIdentity.capture(os.getpid()),
            )
        )
        release = asyncio.Event()
        started = asyncio.Event()
        disk_release = threading.Event()
        agent_data = {
            "name": "Slow test owner",
            "identity": "slow-test",
            "short_name": "slow",
            "run_command": {"*": "/bin/false"},
            "protocol": "acp",
        }

        async def start(agent, target):
            agent.attach_surface(target)

            async def attach():
                started.set()
                await release.wait()
                cursor = TranscriptCursor("test", 0)
                page = TranscriptPage((AssistantTranscript('LOADED-HISTORY-END'),),
                                      cursor, cursor, False, False)
                target.post_message(CommsUpdated(TranscriptSnapshotUpdate(page)))
                target.post_message(AgentReady())

            agent.process.session_task = asyncio.create_task(attach())

        app = ToadApp(project_dir=str(root))
        try:
            async with (
                app.run_test(size=(110, 34)) as pilot,
                release_on_exit(release, disk_release),
            ):
                await pilot.pause()
                source = app.selected_mode
                app.screen._agent = agent_data
                sidebar = app.screen.query_one(CommsSidebar)
                await sidebar.sync_sessions()
                original_read = type(comms.views).viewer_snapshot

                def slow_read(self, *args, **kwargs):
                    if not disk_release.wait(8):
                        raise TimeoutError("Test disk gate was not released")
                    return original_read(self, *args, **kwargs)

                with (
                    patch.object(Agent, "start", start),
                    patch.object(type(comms.views), "viewer_snapshot", slow_read),
                ):
                    mode = await asyncio.wait_for(
                        app.thread_navigation.open(
                            owner_mode=source, project_path=root, target="slow-thread"
                        ),
                        2,
                    )
                    await asyncio.wait_for(started.wait(), 2)
                    await pilot.pause()
                    frame = "\n".join(
                        (strip.text for strip in app.screen._compositor.render_strips())
                    )
                    assert "Loading new thread and history" in frame, frame
                    conversation = app.selected_session.conversation
                    loading = conversation.query_one(ThreadLoading)
                    viewport = conversation.window.content_region
                    assert loading.region.width >= viewport.width - 2
                    assert loading.region.height >= viewport.height - 2
                    assert abs(loading.region.center[1] - viewport.center[1]) <= 3
                    caption = "Loading new thread and history…"
                    painted_line = next(
                        (line for line in frame.splitlines() if caption in line)
                    )
                    caption_center = painted_line.index(caption) + len(caption) // 2
                    assert abs(caption_center - viewport.center[0]) <= 2, (
                        caption_center,
                        viewport.center[0],
                        painted_line,
                    )
                    ring = loading.render().plain.splitlines()
                    ring_rows = [
                        line for line in ring if any((mark in line for mark in "●•·"))
                    ]
                    ring_columns = [
                        index
                        for line in ring_rows
                        for index, char in enumerate(line)
                        if char in "●•·"
                    ]
                    ring_ratio = (max(ring_columns) - min(ring_columns) + 1) / len(
                        ring_rows
                    )
                    assert 1.5 <= ring_ratio <= 2.5
                    large_rows = loading.render().plain.count("\n")
                    assert large_rows >= 6
                    await pilot.resize_terminal(78, 28)
                    await pilot.pause()
                    assert (
                        loading.region.width
                        >= conversation.window.content_region.width - 2
                    )
                    assert loading.render().plain.count("\n") < large_rows
                    await pilot.resize_terminal(110, 34)
                    await pilot.pause()
                    conversation.prompt.focus()
                    await pilot.press("h", "i")
                    assert conversation.prompt.text == "hi"
                    await asyncio.wait_for(app.switch_mode(source), 2)
                    await asyncio.wait_for(app.switch_mode(mode), 2)
                    assert not release.is_set() and (not disk_release.is_set())
                    assert conversation.query(ThreadLoading)
                    release.set()
                    disk_release.set()
                    async with asyncio.timeout(5):
                        while not conversation.agent_ready:
                            await asyncio.sleep(0.02)
                    await pilot.pause()
                    assert not conversation.query(ThreadLoading)
                    assert conversation.prompt.text == "hi"
                    frame = "\n".join(
                        (strip.text for strip in app.screen._compositor.render_strips())
                    )
                    assert "LOADED-HISTORY-END" in frame
        finally:
            release.set()
            disk_release.set()
            await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "async thread open: spinner, typing, and tab switching work before owner and disk reads complete"
    )


if __name__ == "__main__":
    asyncio.run(main())
