"""Goal display permissions and a new nominal case use the same contract."""

from agent_comms.goals import Goal
from agent_comms.ui_model.goal import GoalDisplay, GoalUnavailable, NoGoal, ShowingGoal


def test_each_goal_state_answers_visibility_control_and_snapshot():
    goal = Goal("Keep the objective", "display-state")
    for state, visible, enabled, snapshot in (
        (NoGoal(), False, True, None),
        (ShowingGoal(goal), True, True, goal),
        (GoalUnavailable(goal), True, False, goal),
        (GoalUnavailable(None), True, False, None),
    ):
        assert state.visible == visible, state
        assert state.can_control == enabled, state
        assert state.snapshot == snapshot, state
        assert not state.standby(None), state
        assert state.heading(None), state


def test_a_new_goal_state_needs_only_its_own_declaration():
    goal = Goal("Keep the objective", "display-state")

    class OwnerReconnecting(GoalDisplay):
        can_control = False

        @property
        def snapshot(self):
            return goal

        def heading(self, execution):
            return "Waiting for the owner"

    state = OwnerReconnecting()
    assert state.visible
    assert not state.can_control
    assert state.details_heading(None) == "Waiting for the owner"
