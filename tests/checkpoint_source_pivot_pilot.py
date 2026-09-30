"""Actual saved-resource replacement when an empty native source gets its first file.

Uses private canonical storage and the original application/Window. No input,
ACP runner, native owner or provider is started.
"""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.comms import Comms
from agent_comms.threads import Thread
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.live_output import ResponseStream
from toad.transcript_publication import CheckpointPublication
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    artifacts = Path(os.environ["CHECKPOINT_PIVOT_ARTIFACTS"]).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=artifacts) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        comms = Comms(root / "wire")
        comms.messaging.initialize_private_initial_protocol()
        thread = comms.registry.declare(Thread("source", frozenset(), str(root)))
        comms.registry.declare(Thread("peer", frozenset(), str(root)))
        notice = comms.messaging.send_message("peer", "source", "ORIGINAL_WIRE_NOTICE")
        old_page = comms.transcripts.thread_transcript_page("source")
        assert not old_page.after.session_file
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await view.transcript.suspend()
            agent = Agent(root, AgentDefinition("custody", "custody", {}), None)
            view.set_reactive(type(view).agent, agent)
            agent.coordination = CoordinationChangedUpdate(
                thread.incarnation, str(root / "wire"), os.getpid(), str(root),
                None, None, thread.name, None,
            )
            view.set_reactive(type(view).agent_ready, False)
            old = TranscriptHistory(old_page)
            await view.contents.mount(old)
            await pilot.pause()
            view.set_reactive(type(view).agent_ready, True)
            live = await view.output.append(ResponseStream(), "FIRST_SAVED_NATIVE_RESPONSE")
            await pilot.pause()
            source = root / "first-native.jsonl"
            source.write_text("".join(json.dumps(record) + "\n" for record in (
                {"type": "message", "id": "native-user-original", "message": {
                    "role": "user", "content": "FIRST_SAVED_NATIVE_USER"}},
                {"type": "message", "id": "native-assistant-original", "message": {
                    "role": "assistant", "content": "FIRST_SAVED_NATIVE_RESPONSE"}},
            )))
            installed = comms.registry.declare(replace(thread, session_file=str(source)))
            assert installed.incarnation == thread.incarnation
            page = await agent.get_transcript_page()
            assert page.after.session_file != old_page.after.session_file
            assert not old.accepts_commit(page.after)
            view.window.anchor()
            view.prompt.focus()
            view.transcript.dirty = view.transcript.checkpoint_required = True
            publication = CheckpointPublication(view.transcript, view, view.window, view.contents)
            assert publication.admitted() and publication.native_current()
            task = asyncio.create_task(publication.publish())
            try:
                async with asyncio.timeout(8):
                    while not task.done():
                        await pilot.pause(.02)
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            await pilot.pause()
            histories = view.transcript.histories
            responses = [item for item in view.contents.query(AgentResponse)
                         if item.source == "FIRST_SAVED_NATIVE_RESPONSE"]
            replacement = histories[0]
            paint = "\n".join("".join(segment.text for segment in strip)
                              for strip in app.screen._compositor.render_strips())
            receipt = {
                "old_native_file": old_page.after.session_file,
                "new_native_file": page.after.session_file,
                "registered_histories": len(view.window.histories),
                "direct_histories": len(histories),
                "old_attached": old.is_attached,
                "live_attached": live.is_attached,
                "response_resources": len(responses),
                "frontier_matches": replacement.committed_cursor == page.after,
                "loader_captured_agent": replacement.loader == agent.get_transcript_page,
                "wire_notice_covered": replacement.covers_incoming(notice.seq),
                "native_input_ids": sorted(identity for event in page.events
                                           for identity in event.native_inputs),
                "response_painted": "FIRST_SAVED_NATIVE_RESPONSE" in paint,
                "native_process_started": agent.process.process is not None,
                "native_runner_started": agent.process.runner is not None,
            }
            print(json.dumps(receipt), flush=True)
            (artifacts / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            assert receipt["registered_histories"] == receipt["direct_histories"] == 1
            assert not receipt["old_attached"] and not receipt["live_attached"]
            assert receipt["response_resources"] == 1 and receipt["response_painted"]
            assert receipt["frontier_matches"] and receipt["loader_captured_agent"]
            assert receipt["wire_notice_covered"]
            assert not receipt["native_process_started"] and not receipt["native_runner_started"]
        assert app._exception is None


if __name__ == "__main__":
    asyncio.run(main())
