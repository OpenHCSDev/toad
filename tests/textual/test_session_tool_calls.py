"""Textual-facing: agent tool-call updates reach the ToolCall widget as merged snapshots, and the widget paints the read output."""

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from acp.schema import ToolCall as SDKToolCall
from agent_comms.thread_identity import DeletedThreadIncarnation, UnrecordedThreadIncarnation
from agent_comms.transcript_receipts import AssignedSourceIdentity

from support.agents import peer
from support.coordination import coordination_fact
from toad.acp.tool_calls import SessionToolCalls
from toad.tool_output import ReadToolOutputPart
from toad.widgets.tool_call import ToolCall


def test_tool_scope_uses_the_recorded_member_not_a_nullable_core_property(tmp_path):
    coordination = coordination_fact("worker", tmp_path)
    agent = SimpleNamespace(coordination=coordination)
    tools = SessionToolCalls(agent)
    assert tools.scope == AssignedSourceIdentity(str(tmp_path), coordination.thread)
    agent.coordination = replace(coordination, thread=DeletedThreadIncarnation("worker"))
    assert tools.scope is None
    agent.coordination = replace(coordination, thread=UnrecordedThreadIncarnation("worker"))
    assert tools.scope is None
    agent.coordination = None
    assert tools.scope is None


async def test_tool_start_progress_and_missing_start_in_the_running_app(workspace):
    counts = {"missing_start_constructions": 0}
    constructor = SDKToolCall.__init__.__code__

    def profile(frame, event, arg):
        if event != "call" or frame.f_back is None:
            return
        if frame.f_code is constructor and frame.f_back.f_code is SessionToolCalls.merge.__code__:
            counts["missing_start_constructions"] += 1

    async with workspace.app(size=(110, 35), agent=peer("echo")) as ui:
        view = ui.conversation
        await ui.until(lambda: view.agent is not None, seconds=20, why="the agent to be created")
        agent = view.agent
        await agent.session.settled.wait()
        pid = agent.process.process.pid
        previous = sys.getprofile()
        sys.setprofile(profile)
        try:
            await agent.updates.receive(agent.session_id, {
                "sessionUpdate": "tool_call", "toolCallId": "native-read", "title": "Read file",
                "kind": "read", "status": "pending", "rawInput": {"path": "first.py"},
                "content": [{"type": "content", "content": {"type": "text", "text": "original = 1"}}]})
            await ui.until(lambda: view.query(ToolCall), seconds=20, why="the tool call widget")
            first = agent.tools.calls["native-read"]
            assert type(first) is SDKToolCall
            assert "sessionUpdate" not in first.model_dump(mode="json", by_alias=True)
            await agent.updates.receive(agent.session_id, {
                "sessionUpdate": "tool_call_update", "toolCallId": "native-read", "status": "in_progress"})
            await agent.updates.receive(agent.session_id, {
                "sessionUpdate": "tool_call_update", "toolCallId": "native-read", "status": "completed",
                "rawInput": {"path": "second.txt"}})
            await ui.until(lambda: view.query_one(ToolCall).tool_call.completed, seconds=20,
                           why="the tool call to complete")
            tool = view.query_one(ToolCall)
            assert isinstance(tool.output.parts[0], ReadToolOutputPart)
            assert tool.output.parts[0].path == "second.txt"
            assert first.raw_input == {"path": "first.py"} and first.status == "pending"
            tool.set_expanded(True)
            await tool.output.sync()
            await ui.until_shows("original = 1")
            # The genuine absent-start path still acquires its default.
            await agent.updates.receive(agent.session_id, {
                "sessionUpdate": "tool_call_update", "toolCallId": "missing-start", "status": "completed"})
            assert agent.tools.calls["missing-start"].title == "Tool call"
            assert counts == {"missing_start_constructions": 1}
        finally:
            sys.setprofile(previous)
            await agent.stop()
        assert not Path(f"/proc/{pid}").exists()
    assert workspace.prompts_received() == []
