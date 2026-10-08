"""Actual private sent resources and reconstructed native tool bodies."""

import asyncio
import json
import os
import sys
import threading

from agent_comms.comms import Comms
from agent_comms.pi_payloads import PiToolResult, ToolResultMessage
from agent_comms.threads import Thread
from agent_comms.tools import invoke_tool
from agent_comms.tool_results import ToolDiff
from agent_comms.transcript_events import ToolStartTranscript, ToolEndTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from toad.acp.status import ToolCallStatus
from toad.app import ToadApp
from toad.tool_output import ToolOutput, ToolContentDecoder, PatchToolOutputPart, ReadToolOutputPart
from toad.widgets.outgoing_message import OutgoingMessage
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import ToolCallDiff
from toad.widgets.transcript_fragments import prepare_transcript_fragments
from toad.widgets.transcript_history import TranscriptHistory


def test_saved_output_parts_and_sent_resource_survive_native_reconstruction(tmp_path, monkeypatch):
    async def mounted():
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
        for name in ("sender", "recipient"):
            service.registry.declare(Thread(name, frozenset(), str(tmp_path)))
        original = invoke_tool(service, "comms_send", {
            "from": "sender", "to": "recipient", "body": "Original private sent resource",
        })
        raw = dict(content=[dict(type="text", text=json.dumps(original))], details=original)
        sent = PiToolResult.from_wire(raw).sent_message(True)
        saved = ToolResultMessage.from_wire(dict(role="toolResult", toolCallId="saved-send",
                                                 toolName="comms_send", isError=False, **raw))
        patch = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n"
        source = (*saved.transcript_events(None),
                  ToolEndTranscript(tool_call_id="saved-edit", tool_name="edit", diff=ToolDiff(patch)),
                  ToolStartTranscript(tool_call_id="saved-read", tool_name="read", raw_input={"path": "file.py"}),
                  ToolEndTranscript(tool_call_id="saved-read", tool_name="read", text="original = 1"))
        counts = {"ui_part_acquisitions": 0, "ui_sent_decodes": 0}
        ui_thread = threading.get_ident()
        codes = {ToolOutput.capture_parts.__code__: "ui_part_acquisitions",
                 ToolContentDecoder.text_resource.__code__: "ui_sent_decodes"}

        def profile(frame, event, arg):
            if event == "call" and threading.get_ident() == ui_thread and frame.f_code in codes:
                counts[codes[frame.f_code]] += 1

        app = ToadApp(project_dir=str(tmp_path))
        async with app.run_test(size=(110, 40)) as pilot:
            await app.selected_session.wait_content_ready()
            previous = sys.getprofile()
            sys.setprofile(profile)
            try:
                fragments = await prepare_transcript_fragments(source, app.render_processes)
                cursor = TranscriptCursor("original-private-tool-output", 3)
                history = TranscriptHistory(TranscriptPage(source, cursor, cursor, False, False), fragments=fragments)
                await app.selected_session.conversation.post(history)
                await pilot.pause()
                sent_body, patch_body, read_body = history.fragment_views
                sent_tool = sent_body.query_one(ToolCall)
                sent_tool.set_expanded(True)
                await sent_tool.output.sync()
                assert sent_tool.query_one(OutgoingMessage).event == sent
                assert sent_tool.output.parts == fragments[0].output_parts
                native_patch = patch_body.query_one(ToolCall).output.parts[0]
                source_patch = fragments[1].output_parts[0]
                assert isinstance(native_patch, PatchToolOutputPart)
                assert native_patch.preparation is not source_patch.preparation
                patch_tool = patch_body.query_one(ToolCall)
                patch_tool.set_expanded(True)
                await patch_tool.output.sync()
                await asyncio.wait_for(patch_tool.query_one(ToolCallDiff).prepared.wait(), 20)
                assert source_patch.preparation.warmup is None
                for body in history.fragment_views:
                    await body.recompose()
                await pilot.pause()
                rebuilt_sent = sent_body.query_one(ToolCall)
                rebuilt_sent.set_expanded(True)
                await rebuilt_sent.output.sync()
                assert rebuilt_sent.query_one(OutgoingMessage).event == sent
                rebuilt_patch = patch_body.query_one(ToolCall).output.parts[0]
                assert rebuilt_patch.source == patch
                assert rebuilt_patch.preparation is not native_patch.preparation
                assert rebuilt_patch.preparation is not source_patch.preparation
                assert counts == {"ui_part_acquisitions": 0, "ui_sent_decodes": 0}
                # The independently changing live call still owns one capture.
                # Recomposition cannot reinterpret it or retain the old filename.
                read_tool = read_body.query_one(ToolCall)
                changed = read_tool.tool_call.call.model_copy(update={"raw_input": {"path": "notes.txt"}})
                await read_tool.update_tool_call(ToolCallStatus.from_acp(changed))
                assert isinstance(read_tool.output.parts[0], ReadToolOutputPart)
                assert read_tool.output.parts[0].path == "notes.txt"
                await read_tool.recompose()
                assert read_tool.output.parts[0].path == "notes.txt"
                assert counts == {"ui_part_acquisitions": 1, "ui_sent_decodes": 0}
                assert app._exception is None
                print({**counts, "saved_native_classifications": 0, "saved_sent_decodes": 0,
                       "reconstructed_bodies": 3, "private_backend_sends": 1, "provider_inputs": 0}, flush=True)
            finally:
                sys.setprofile(previous)

    asyncio.run(mounted())
