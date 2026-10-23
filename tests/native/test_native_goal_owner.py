"""Goal requests reach the managed native owner through Toad's real controller."""

import pytest
from agent_comms.goal_actions import SetGoalAction
from agent_comms.runtime_requests import GoalHistoryReply
from support.native import native_session


async def test_setting_a_goal_reaches_the_native_provider(workspace, native_package):
    async with native_session(workspace) as native:
        native.provider.hold_next_request()
        goal = await native.agent.update_goal(SetGoalAction, "Finish the task")
        assert goal.state.declared_name == "active"
        await native.ui.until(native.provider.entered.is_set, seconds=30,
                              why="the managed owner begins the goal")
        assert native.comms.registry.require(native.thread).goal == goal
        native.provider.release()


async def test_editing_a_goal_keeps_its_identity_and_refuses_a_stale_edit(workspace, native_package):
    async with native_session(workspace) as native:
        agent, comms, session = native.agent, native.comms, native.thread
        first = await agent.update_goal(SetGoalAction, "First objective")
        changed = await agent.edit_goal(first, "Revised objective")
        assert changed.id == first.id
        assert changed.revision == first.revision + 1
        assert changed.state == first.state
        assert comms.registry.require(session).goal == changed
        with pytest.raises(ValueError):
            await agent.edit_goal(first, "Stale overwrite")
        history: GoalHistoryReply = await agent.get_goal_history(changed.id)
        assert any(entry.after.shows_document and entry.after.require().text == "First objective"
                   for entry in history.history)
        assert any(entry.before.shows_document and entry.before.require().text == "First objective"
                   and entry.after.require().text == "Revised objective" for entry in history.history)
        assert not any(entry.after.shows_document and entry.after.require().text == "Stale overwrite"
                       for entry in history.history)
        snapshot = await agent.get_goal_snapshot()
        assert snapshot.goal == changed and snapshot.execution.goal_id == changed.id
