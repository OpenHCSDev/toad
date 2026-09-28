"""A blocked goal offers explicit Retry and reaches the executing owner."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.goal_states import ActiveGoal, BlockedGoal
from agent_comms.goals import Goal
from runtime_fixture import ToadApp
from toad.widgets.goal_bar import GoalBar


class FakeAgent:
    def __init__(self, goal: Goal):
        self.goal = goal
        self.actions: list[str] = []

    async def update_goal(self, action: str, text: str = "") -> Goal:
        self.actions.append(action)
        self.goal = Goal(self.goal.text, self.goal.id, state=ActiveGoal())
        return self.goal

    async def get_goal_snapshot(self):
        return self.goal, None

    async def stop(self) -> None:
        pass


async def mounted_retry_control(root: Path) -> None:
    app = ToadApp(project_dir=str(root))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        view = app.screen.conversation
        goal = Goal("Learn architectural factoring", "goal-control", state=BlockedGoal(block_reason="Original turn failed"))
        fake = FakeAgent(goal)
        view.set_reactive(type(view).agent, fake)
        view.agent_ready = True
        view.goal = goal
        await pilot.pause()
        bar = view.query_one(GoalBar)
        assert str(bar.query_one("#goal-toggle").render()) == "Retry"
        await pilot.click("#goal-toggle")
        await pilot.pause()
        assert fake.actions == ["retry"]
        assert view.goal.state.declared_name == "active"


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-goal-retry-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        await mounted_retry_control(root)
    print("goal retry: mounted explicit Retry control passed")


if __name__ == "__main__":
    asyncio.run(main())
