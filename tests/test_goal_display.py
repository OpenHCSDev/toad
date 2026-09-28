"""Goal display permissions and a new nominal case use the same widget contract."""

import ast
from pathlib import Path
import unittest

from agent_comms.goals import Goal
from toad.goal_display import GoalDisplay, GoalUnavailable, NoGoal, ShowingGoal


class GoalDisplayTest(unittest.TestCase):
    def test_states_and_new_case(self):
        goal = Goal("Keep the objective", "display-state")
        for state, visible, enabled, snapshot in (
            (NoGoal(), False, True, None),
            (ShowingGoal(goal), True, True, goal),
            (GoalUnavailable(goal), True, False, goal),
            (GoalUnavailable(None), True, False, None),
        ):
            with self.subTest(state=state):
                self.assertEqual(state.visible, visible)
                self.assertEqual(state.can_control, enabled)
                self.assertEqual(state.snapshot, snapshot)
                self.assertFalse(state.standby(None))
                self.assertTrue(state.heading(None))

        class OwnerReconnecting(GoalDisplay):
            can_control = False

            @property
            def snapshot(self):
                return goal

            def heading(self, execution):
                return "Waiting for the owner"

        state = OwnerReconnecting()
        self.assertTrue(state.visible)
        self.assertFalse(state.can_control)
        self.assertEqual(state.details_heading(None), "Waiting for the owner")

    def test_widgets_have_one_goal_state(self):
        source = Path(__file__).resolve().parents[1] / "src/toad"
        for relative, retired in (
            ("widgets/goal_bar.py", {"goal", "unavailable"}),
            ("screens/goal_details.py", {"goal", "unavailable"}),
            ("widgets/conversation.py", {"goal", "goal_unavailable"}),
        ):
            tree = ast.parse((source / relative).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    if node.value.id == "self":
                        self.assertNotIn(node.attr, retired, relative)
                if isinstance(node, ast.ClassDef):
                    for declaration in node.body:
                        if isinstance(declaration, ast.AnnAssign) and isinstance(declaration.target, ast.Name):
                            self.assertNotIn(declaration.target.id, retired, relative)


if __name__ == "__main__":
    unittest.main()
