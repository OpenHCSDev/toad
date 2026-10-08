"""Saved ACP acquisition belongs to the original prepared transcript resource."""

import asyncio
import os
import pickle
import sys
import threading
import time

from agent_comms.comms import Comms
from agent_comms.tool_results import ToolDiff
from agent_comms.transcript_events import AssistantTranscript, ToolStartTranscript, ToolEndTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual import events
from textual.geometry import Offset
from toad.acp.status import ToolCallStatus
from toad.app import ToadApp
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import TextContent
from toad.widgets.transcript_fragments import ToolTranscriptFragment, prepare_transcript_fragments, transcript_fragments
from toad.widgets.transcript_history import TranscriptHistory, transcript_blocks


def test_recorded_grouping_retains_final_call_and_original_diff():
    patch = "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-old\n+new\n"
    source = (
        ToolStartTranscript(tool_call_id="edit", tool_name="edit", raw_input={"path": "example.py"}),
        AssistantTranscript("Between original tool events"),
        ToolEndTranscript(tool_call_id="edit", tool_name="edit", text="Original error", ok=False, diff=ToolDiff(patch)),
        ToolEndTranscript(tool_call_id="orphan", tool_name="bash", text="End without start"),
    )
    fragments = transcript_fragments(source)
    first, text, orphan = pickle.loads(pickle.dumps(fragments))
    assert isinstance(first, ToolTranscriptFragment)
    assert first.tool_call.failed and not first.tool_call.completed
    assert first.tool_call.call.raw_input == {"path": "example.py"}
    assert first.tool_call.call.content[0].content.resource.text == patch
    assert first.tool_call.call.content[1].content.text == "Original error"
    assert first.retained_bytes > len(patch)
    assert text.events == (source[1],)
    assert orphan.tool_call.completed and orphan.tool_call.call.raw_input is None
    blocks = transcript_blocks(source)
    assert isinstance(blocks[0], ToolCall) and blocks[0].tool_call.failed
    assert blocks[2].tool_call.call.tool_call_id == "orphan"


def test_saved_page_acquires_tools_off_ui_and_reconstruction_borrows_them(tmp_path, monkeypatch):
    async def mounted():
        project = tmp_path / "project"
        project.mkdir()
        service = Comms(tmp_path / "wire")
        service.messaging.initialize_private_initial_protocol()
        for key in tuple(os.environ):
            if key.startswith("AGENT_COMMS_"):
                monkeypatch.delenv(key)
        for key, value in {"AGENT_COMMS_ROOT": service.root,
                           "XDG_CONFIG_HOME": tmp_path / "config",
                           "XDG_STATE_HOME": tmp_path / "state",
                           "XDG_DATA_HOME": tmp_path / "data"}.items():
            monkeypatch.setenv(key, str(value))
        source = tuple(event for index in range(16) for event in (
            ToolStartTranscript(tool_call_id=f"saved-{index}", tool_name="bash",
                                raw_input={"command": f"Original saved command {index}",
                                           "original": list(range(2000))}),
            ToolEndTranscript(tool_call_id=f"saved-{index}", tool_name="bash",
                              text=(f"Original saved output {index} 界\n" * 2000), ok=index != 14),
        ))
        counts = {"ui_saved_acquisitions": 0}
        ui_thread = threading.get_ident()
        acquire_code = ToolCallStatus.from_transcript.__func__.__code__

        def profile(frame, event, arg):
            if event == "call" and frame.f_code is acquire_code and threading.get_ident() == ui_thread:
                counts["ui_saved_acquisitions"] += 1

        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            previous_profile = sys.getprofile()
            sys.setprofile(profile)
            try:
                fragments = await prepare_transcript_fragments(source, app.render_processes)
                assert len(fragments) == 16 and all(isinstance(item, ToolTranscriptFragment) for item in fragments)
                cursor = TranscriptCursor("original-saved-tools", 16)
                history = TranscriptHistory(TranscriptPage(source, cursor, cursor, False, False), fragments=fragments)
                conversation = app.selected_session.conversation
                await conversation.post(history)
                await pilot.pause()
                bodies = history.fragment_views
                assert bodies
                assert len(bodies) == sum(page.stop - page.start for page in history.pages)
                for body in bodies:
                    recorded = body.fragment.tool_call
                    assert body.query_one(ToolCall).tool_call is recorded
                    await body.recompose()
                    assert body.query_one(ToolCall).tool_call is recorded
                tool = bodies[-1].query_one(ToolCall)
                tool.set_expanded(True)
                await tool.output.sync()
                content = tool.query_one(TextContent)
                await asyncio.wait_for(content.wait_ready(), 20)
                await pilot.pause()
                assert "Original saved output 15" in content.prepared_content.text
                editor = conversation.prompt.prompt_text_area
                editor.focus(scroll_visible=False)
                started = time.perf_counter()
                await pilot.press("d", "r", "a", "f", "t")
                typing_ms = (time.perf_counter() - started) * 1000
                assert editor.text == "draft"
                window = conversation.window
                position = window.content_region.offset + Offset(3, 3)
                for direction in (events.MouseScrollUp, events.MouseScrollDown):
                    app.post_message(direction(None, position.x, position.y, 0, 0, 0, False, False, False))
                    await pilot.pause()
                assert editor.text == "draft" and counts["ui_saved_acquisitions"] == 0
                assert app._exception is None
                print({**counts, "prepared_tools": len(fragments), "reconstructed_tools": len(bodies),
                       "draft_ms": round(typing_ms, 1), "provider_inputs": 0}, flush=True)
            finally:
                sys.setprofile(previous_profile)

    asyncio.run(mounted())
