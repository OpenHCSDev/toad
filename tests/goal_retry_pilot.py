"""A blocked goal offers explicit Retry and reaches the executing owner."""

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent_comms import Goal
from agent_comms.acp import CommsAgent
from agent_comms.operations import wire
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.widgets.goal_bar import GoalBar


class FakeAgent:
    def __init__(self, goal: Goal):
        self.goal = goal
        self.actions: list[str] = []

    async def update_goal(self, action: str, text: str = "") -> Goal:
        self.actions.append(action)
        self.goal = Goal(self.goal.text, self.goal.id, status="active")
        return self.goal

    async def stop(self) -> None:
        pass


async def mounted_retry_control(root: Path) -> None:
    app = ToadApp(project_dir=str(root))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        view = app.screen.conversation
        goal = Goal("Learn architectural factoring", "goal-control", status="blocked")
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
        assert view.goal.status == "active"


async def owner_retry_route(root: Path) -> None:
    comms = wire(root / "wire")
    owner = CommsAgent(comms, agent_bin="pi", runtime_enabled=True)
    owner._ensure_live_drain = lambda _session: None
    owner._schedule_wake = lambda _session: None
    owner._schedule_goal = lambda _session: None
    project = root / "project"
    project.mkdir()
    await owner.new_session(str(project))
    toad_agent = SimpleNamespace(_coordination_root=comms.root, _coordination_thread="project")
    goal = await Agent.update_goal(toad_agent, "set", "Learn architectural factoring")
    store = owner._open_goal_store()
    assert store.snapshot(goal.id).state == "ready"
    assert store.ready_grant(goal.id, 1)
    attempt = store.reserve(goal.id, 1)
    store.claim_launch(attempt)
    store.record_failed(attempt, "Original turn failed")
    comms.update_goal("project", "blocked", goal_id=goal.id)
    try:
        resumed = await Agent.update_goal(toad_agent, "retry")
        assert resumed.id == goal.id and resumed.status == "active"
        assert store.snapshot(goal.id).number == 2
        assert store.ready_grant(goal.id, 2)
    finally:
        await owner.shutdown()


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
        await owner_retry_route(root)
    print("goal retry: mounted control and owner grant passed")


if __name__ == "__main__":
    asyncio.run(main())
