"""Goal display permissions and a new nominal case use the same contract."""

from agent_comms.goal_presentation import IdleGoalExecution
from agent_comms.goals import GoalDeclaration, NoGoal
from agent_comms.ui_model.goal import GoalDisplay, GoalUnavailable
from support.goals import published_goal


def test_each_goal_state_answers_visibility_control_and_snapshot():
    goal = published_goal("Keep the objective", "display-state")
    idle = IdleGoalExecution()
    for state, visible, enabled, snapshot in (
        (NoGoal(), False, False, NoGoal()),  # nothing to control: Core answers a control with "This goal has been cleared."
        (goal, True, True, goal),
        (GoalUnavailable(goal), True, False, goal),
        (GoalUnavailable(NoGoal()), True, False, NoGoal()),
    ):
        assert state.visible == visible, state
        assert state.can_control == enabled, state
        assert state.snapshot == snapshot, state
        assert not state.standby(idle), state
        assert state.heading(idle), state


def test_a_new_goal_state_needs_only_its_own_declaration():
    goal = published_goal("Keep the objective", "display-state")

    class OwnerReconnecting(GoalDisplay):
        can_control = False
        visible = True

        @property
        def snapshot(self) -> GoalDeclaration:
            return goal

        def heading(self, execution):
            return "Waiting for the owner"

        def standby(self, execution):
            return False

        def action_failure(self, error):
            return str(error)

    state = OwnerReconnecting()
    assert state.visible
    assert not state.can_control
    assert state.details_heading(IdleGoalExecution()) == "Waiting for the owner"
