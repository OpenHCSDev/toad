"""Toad's goal requests reach the real owner: setting a goal makes it launchable; an edit keeps its identity."""

import pytest
from agent_comms.goal_actions import SetGoalAction
from agent_comms.goal_attempts import GoalAttemptStore

from support.native import owner_server, start_private_native_wire
from toad.acp.transcript_reader import CoordinationTranscriptReader


class InProcessReader(CoordinationTranscriptReader):
    """Asks the owner directly, as Core's observation service would."""

    def __init__(self, comms):
        super().__init__()
        self.comms = comms

    async def read(self, request):
        return await request.ask(self.comms)


async def test_setting_a_goal_makes_it_ready_to_launch(workspace, native_package, monkeypatch):
    monkeypatch.setenv("AGENT_COMMS_AGENT_MODELS", "openrouter/fake")
    comms = start_private_native_wire(workspace.roots.wire, native_package)
    owner = owner_server(comms, native_package)
    try:
        session = (await owner.new_session(cwd=str(workspace.project))).session_id
        agent = workspace.agents.detached_agent()
        agent.coordination = comms.configuration.answer(session)
        goal = await agent.update_goal(SetGoalAction, "Finish the task")
        assert goal is not None and goal.state.declared_name == "active"
        assert goal.text == "Finish the task"
        generation = GoalAttemptStore(comms.root / "goal-private").snapshot(goal.id)
        assert generation is not None and generation.lifecycle.ready
        assert owner.turns.goals.open_goal_store().ready_grant(goal.id, generation.number)
        assert comms.registry.require(session).goal == goal
    finally:
        await owner.shutdown()


async def test_editing_a_goal_keeps_its_identity_and_refuses_a_stale_edit(workspace, native_package, monkeypatch):
    monkeypatch.setenv("AGENT_COMMS_AGENT_MODELS", "openrouter/fake")
    comms = start_private_native_wire(workspace.roots.wire, native_package)
    owner = owner_server(comms, native_package)
    try:
        session = (await owner.new_session(cwd=str(workspace.project))).session_id
        agent = workspace.agents.detached_agent()
        agent.coordination = comms.configuration.answer(session)
        agent.controller.transcripts = InProcessReader(comms)
        first = await agent.update_goal(SetGoalAction, "First objective")
        changed = await agent.edit_goal(first, "Revised objective")
        assert changed.id == first.id
        assert changed.revision == first.revision + 1
        assert changed.state.declared_name == first.state.declared_name
        assert comms.registry.require(session).goal == changed
        with pytest.raises(ValueError):
            await agent.edit_goal(first, "Stale overwrite")
        history = await agent.get_goal_history(changed.id)
        assert any(entry["after"] and entry["after"]["text"] == "First objective" for entry in history)
        assert any(entry["before"] and entry["before"]["text"] == "First objective"
                   and entry["after"]["text"] == "Revised objective" for entry in history)
        assert not any(entry["after"] and entry["after"]["text"] == "Stale overwrite" for entry in history)
        snapshot = await agent.get_goal_snapshot()
        assert snapshot.goal == changed and snapshot.execution.goal_id == changed.id
    finally:
        await owner.shutdown()
