"""RED: Pi's *automatic mid-turn* compaction must reach Toad with status and summary.

Offline native-RPC-shaped stdout fixture, not provider delivery. Pi 0.85.1
rpc.md emits compaction_start(reason=threshold) and compaction_end(result.summary)
even inside a turn. This checks the real backend -> ACP -> Toad path rather than
fabricating a manual /compact command or inferring compaction from usage reset.
"""

import asyncio
import os
from pathlib import Path
import tempfile
import time

from agent_comms import backend
from agent_comms.acp import CommsAgent
from agent_comms.operations import wire
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.acp.messages import TurnStarted
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation, TurnActivity


SUMMARY = "## Decisions\n\n" + "- AUTO-COMPACTION-PRESERVED-DECISIONS\n" * 30 + "\n## Next\nContinue."


class CaptureClient:
    def __init__(self):
        self.updates = []

    async def session_update(self, *, session_id, update):
        assert session_id == "fixture"
        self.updates.append(update)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-auto-compact-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        records = [
            {"type": "message_end", "message": {"role": "assistant", "stopReason": "toolUse"}},
            {"type": "tool_execution_start", "toolCallId": "tool-1", "toolName": "bash", "args": {}},
            {"type": "tool_execution_end", "toolCallId": "tool-1", "toolName": "bash",
             "result": {"content": [{"type": "text", "text": "done"}]}, "isError": False},
            {"type": "compaction_start", "reason": "threshold"},
            {"type": "compaction_progress", "reason": "threshold", "chunkIndex": 2},
            {"type": "compaction_end", "reason": "threshold", "aborted": False,
             "willRetry": False, "result": {"summary": SUMMARY, "firstKeptEntryId": "saved-1",
              "tokensBefore": 150000, "estimatedTokensAfter": 32000}},
            {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop",
             "content": [{"type": "text", "text": "Answer after compaction"}]}},
            {"type": "agent_settled"},
            {"type": "response", "command": "get_session_stats", "success": True,
             "data": {"contextUsage": {"tokens": None, "contextWindow": 272000}}},
        ]
        stub = root / "pi-rpc-fixture"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            + f"CAPABILITY = {backend.NATIVE_INPUT_CAPABILITY!r}\n"
            + f"RECORDS = {records!r}\n"
            + """import json
import sys

def emit(value):
    print(json.dumps(value), flush=True)

preflight = json.loads(sys.stdin.readline())
emit({"type": "response", "id": preflight["id"], "command": "get_state",
      "success": True, "data": {"nativeInputProofCapability": CAPABILITY}})
prompt = json.loads(sys.stdin.readline())
emit({"type": "response", "id": prompt["id"], "command": "prompt", "success": True})
emit({"type": "message_start", "message": {"role": "user",
      "content": prompt["message"], "inputId": prompt["inputId"]}})
for record in RECORDS:
    emit(record)
"""
        )
        stub.chmod(0o700)
        events = [event async for event in backend.stream_agent_events(
            str(stub), [], "task", str(root)
        )]
        assert events[-1].get("type") == "done" and events[-1].get("ok") is True, events
        start = next((e for e in events if e.get("type") == "compaction_start"), None)
        end = next((e for e in events if e.get("type") == "compaction_end"), None)
        assert start is not None and start.get("reason") == "threshold", (
            "Backend swallowed Pi's automatic compaction_start before ACP: "
            + repr([e.get("type") for e in events]))
        assert end is not None and end.get("summary") == SUMMARY, (
            "Backend swallowed Pi's automatic compaction_end summary before ACP: "
            + repr([e.get("type") for e in events]))

        server = CommsAgent(wire(root / "wire"))
        client = CaptureClient()
        await server._emit_event("fixture", start, client=client)
        start_updates = list(client.updates)
        progress = next(e for e in events if e.get("type") == "compaction_progress")
        await server._emit_event("fixture", progress, client=client)
        progress_updates = client.updates[len(start_updates):]
        assert progress_updates, "ACP discarded native compaction progress"
        await server._emit_event("fixture", end, client=client)
        end_updates = client.updates[len(start_updates) + len(progress_updates):]
        assert start_updates, "ACP did not forward automatic compaction-start activity"
        assert end_updates and any(
            update.model_dump(by_alias=True).get("_meta", {}).get("agentComms", {})
            .get("compaction", {}).get("summary") == SUMMARY for update in end_updates
        ), "ACP did not forward the exact automatic compaction summary"

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = Agent(root, {"name": "Fixture", "identity": "fixture",
                                 "short_name": "fixture", "run_command": {"*": "true"},
                                 "protocol": "acp"}, "fixture")
            agent._message_target = view
            view.set_reactive(Conversation.agent, agent)
            view.post_message(TurnStarted("active-turn", time.time() - 3, "working", "Thinking"))
            await pilot.pause()
            assert view.busy_count == 1
            for update in start_updates:
                agent.rpc_session_update("fixture", update.model_dump(by_alias=True, exclude_none=True))
            await pilot.pause()
            status = view.query_one(TurnActivity)
            assert "Compacting context" in status.render().plain, (
                "Automatic compaction left an active Toad turn without activity indication",
                status.render().plain)
            assert view.busy_count == 1, "Compaction is inside the active turn, not a second turn"
            for update in progress_updates:
                agent.rpc_session_update("fixture", update.model_dump(by_alias=True, exclude_none=True))
            await pilot.pause()
            assert "step 2 completed" in status.render().plain
            assert not any(isinstance(block, AgentResponse) for block in view.contents.children)
            for update in end_updates:
                agent.rpc_session_update("fixture", update.model_dump(by_alias=True, exclude_none=True))
            await pilot.pause()
            summaries = [block for block in view.contents.children
                         if isinstance(block, AgentResponse) and SUMMARY in block.source]
            assert len(summaries) == 1, "Automatic compaction summary was not displayed once"
            assert view.busy_count == 1 and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("auto compaction: Pi start/end -> backend -> ACP -> active Toad activity + one summary")


if __name__ == "__main__":
    asyncio.run(main())
