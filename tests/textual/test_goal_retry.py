"""Textual-facing: the goal bar's Retry control is a mounted button that reaches the goal owner."""

from agent_comms.goal_actions import RetryGoalAction
from agent_comms.goal_states import BlockedGoal
from agent_comms.goals import Goal
from agent_comms.ui_model.goal import GoalDisplay

from support.goals import ScriptedGoalOwner
from toad.widgets.goal_bar import GoalBar


async def test_blocked_goal_offers_retry_and_retry_reaches_the_owner(workspace):
    async with workspace.app(size=(100, 30)) as ui:
        view = ui.conversation
        goal = Goal("Learn architectural factoring", "goal-control",
                    state=BlockedGoal(block_reason="Original turn failed"))
        owner = ScriptedGoalOwner(workspace.project, goal)
        ui.attach_agent(owner)
        view.agent_ready = True
        view.goal_display = GoalDisplay.current(goal)
        bar = view.query_one(GoalBar)
        assert str(bar.query_one("#goal-toggle").render()) == "Retry"
        await ui.until_shows("Retry")
        await ui.click("Retry")
        await ui.until(lambda: owner.requests, why="the retry request at the owner")
        assert owner.requests == [("update", RetryGoalAction)]
        await ui.until(lambda: view.goal_display.snapshot.state.declared_name == "active",
                       why="the goal shown as active")
