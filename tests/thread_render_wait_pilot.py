"""Post-spinner transcript preparation must not block draft input or tab exit."""
from agent_comms.acp_extension import TranscriptSnapshotUpdate
from toad.acp.messages import CommsUpdated

import asyncio
import os
import sys
import tempfile
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
from worker_preview_pilot import GateRenderer

from toad.acp.agent import Agent
from toad.agent import AgentReady
from toad.render_tasks import TranscriptRenderTask
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import ThreadLoading


class ReplayGate(GateRenderer):
    async def submit(self, task):
        if isinstance(task, TranscriptRenderTask):
            self.entered.set()
            await self.release.wait()
        return await self.pool.submit(task)


@asynccontextmanager
async def release_gates(renderer, dispatch):
    try:
        yield
    finally:
        dispatch.set()
        renderer.release.set()


async def main():
    output = sys.stdout

    def trace(stage):
        if os.environ.get("TOAD_TEST_TRACE"):
            print(stage, file=output, flush=True)

    with tempfile.TemporaryDirectory(prefix="toad-replay-worker-wait-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        wire(root / "wire").threads.register(
            Thread(
                "replay",
                frozenset(),
                str(root),
                process_identity=ProcessIdentity.capture(os.getpid()),
            )
        )
        events = tuple((AssistantTranscript("Paragraph.\n\n" * 100) for _ in range(20)))
        events += (AssistantTranscript("PREPARED_REPLAY_END"),)
        page = TranscriptPage(
            events,
            TranscriptCursor("fixture", 0),
            TranscriptCursor("fixture", len(events)),
            False,
            False,
        )
        dispatch = asyncio.Event()

        async def start(agent, target):
            agent.attach_surface(target)

            async def deliver():
                await dispatch.wait()
                target.post_message(CommsUpdated(TranscriptSnapshotUpdate(page)))
                target.post_message(AgentReady())

            agent.process.session_task = asyncio.create_task(deliver())

        renderer = ReplayGate()
        app = ToadApp(project_dir=str(root), renderer=renderer)
        trace("app created")
        try:
            with patch.object(Agent, "start", start):
                async with (
                    app.run_test(size=(110, 35)) as pilot,
                    release_gates(renderer, dispatch),
                ):
                    await pilot.pause()
                    trace("initial screen")
                    owner = app.current_mode
                    app.screen._agent = {
                        "name": "Fixture",
                        "identity": "fixture",
                        "short_name": "fixture",
                        "run_command": {"*": "/bin/false"},
                        "protocol": "acp",
                    }
                    mode = await app.open_thread_session(
                        owner_mode=owner, project_path=root, target="replay"
                    )
                    trace("opened thread")
                    conversation = app.screen.conversation
                    await pilot.pause()
                    assert conversation.query(ThreadLoading)
                    dispatch.set()
                    trace("dispatched replay")
                    await asyncio.wait_for(renderer.entered.wait(), 3)
                    trace("renderer gated")
                    conversation.prompt.focus()
                    await asyncio.wait_for(app._press_keys("draft"), 2)
                    async with asyncio.timeout(2):
                        while conversation.prompt.text != "draft":
                            await asyncio.sleep(0.01)
                    assert conversation.prompt.text == "draft"
                    trace("typed")
                    await asyncio.wait_for(app.switch_mode(owner), 2)
                    trace("left tab")
                    assert not renderer.release.is_set()
                    renderer.release.set()
                    await asyncio.wait_for(app.switch_mode(mode), 2)
                    trace("returned tab")
                    async with asyncio.timeout(15):
                        while not conversation.agent_ready:
                            await asyncio.sleep(0.01)
                    await pilot.pause()
                    trace("replay ready")
                    assert not conversation.query(ThreadLoading)
                    assert any(
                        (
                            "PREPARED_REPLAY_END" in response.source
                            for response in conversation.query(AgentResponse)
                        )
                    )
                    assert (
                        conversation.prompt.text == "draft" and app._exception is None
                    )
        finally:
            dispatch.set()
            renderer.release.set()
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "post-spinner worker gate: large replay uses shared renderer; typing, tab exit/return and draft survive"
    )


if __name__ == "__main__":
    asyncio.run(main())
