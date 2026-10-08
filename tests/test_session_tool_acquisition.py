"""Admitted SDK tool snapshots reach the original native consumer once."""

import asyncio
import os
from pathlib import Path
import shlex
import sys

from acp.schema import ToolCall as SDKToolCall
from toad.acp.tool_calls import SessionToolCalls
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.widgets.tool_call import ToolCall
from toad.tool_output import ReadToolOutputPart


def test_admitted_tool_start_progress_and_missing_start_in_actual_app(tmp_path, monkeypatch):
    async def mounted():
        from agent_comms.comms import Comms

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
        definition = AgentDefinition.decode({
            "name": "Original tool acquisition", "identity": "tool-acquisition",
            "run_command": {"*": shlex.join((sys.executable, str(Path(__file__).with_name("acp_completion_server.py"))))},
        })
        app = ToadApp(project_dir=str(tmp_path), agent_data=definition)
        counts = {"missing_start_constructions": 0}
        constructor = SDKToolCall.__init__.__code__

        def profile(frame, event, arg):
            if event != "call" or frame.f_back is None:
                return
            caller = frame.f_back.f_code
            if frame.f_code is constructor and caller is SessionToolCalls.merge.__code__:
                counts["missing_start_constructions"] += 1

        async with app.run_test(size=(110, 35)) as pilot:
            view = app.selected_session.conversation
            async with asyncio.timeout(20):
                while view.agent is None:
                    await pilot.pause()
                agent = view.agent
                await agent.session.settled.wait()
            child = agent.process.process
            pid = child.pid
            previous = sys.getprofile()
            sys.setprofile(profile)
            try:
                original = {"sessionUpdate": "tool_call", "toolCallId": "native-read", "title": "Original read",
                            "kind": "read", "status": "pending", "rawInput": {"path": "first.py"},
                            "content": [{"type": "content", "content": {"type": "text", "text": "original = 1"}}]}
                await agent.updates.receive(agent.session_id, original)
                async with asyncio.timeout(20):
                    while not view.query(ToolCall):
                        await pilot.pause()
                first = agent.tools.calls["native-read"]
                assert type(first) is SDKToolCall
                assert "sessionUpdate" not in first.model_dump(mode="json", by_alias=True)
                await agent.updates.receive(agent.session_id, {
                    "sessionUpdate": "tool_call_update", "toolCallId": "native-read", "status": "in_progress"})
                await agent.updates.receive(agent.session_id, {
                    "sessionUpdate": "tool_call_update", "toolCallId": "native-read", "status": "completed",
                    "rawInput": {"path": "second.txt"}})
                async with asyncio.timeout(20):
                    while not view.query_one(ToolCall).tool_call.completed:
                        await pilot.pause()
                tool = view.query_one(ToolCall)
                assert isinstance(tool.output.parts[0], ReadToolOutputPart)
                assert tool.output.parts[0].path == "second.txt"
                assert first.raw_input == {"path": "first.py"} and first.status == "pending"
                tool.set_expanded(True)
                await tool.output.sync()
                await pilot.pause()
                assert "original = 1" in "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                # The genuine absent-start path still acquires its default.
                await agent.updates.receive(agent.session_id, {
                    "sessionUpdate": "tool_call_update", "toolCallId": "missing-start", "status": "completed"})
                assert agent.tools.calls["missing-start"].title == "Tool call"
                assert counts == {"missing_start_constructions": 1}
                assert app._exception is None
                print({**counts, "native_read_painted": True, "prior_snapshot_preserved": True,
                       "provider_inputs": 0}, flush=True)
            finally:
                sys.setprofile(previous)
                await agent.stop()
            assert not Path(f"/proc/{pid}").exists()
        assert not (tmp_path / "completion-wire.jsonl").exists()

    asyncio.run(mounted())
