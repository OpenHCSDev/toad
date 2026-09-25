"""The Toad Set Goal action must create the owner's private launch authority."""

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent_comms.acp import CommsAgent
from agent_comms.goal_attempts import GoalAttemptStore
from agent_comms.operations import wire
from toad.acp.agent import Agent


async def owner_set_route(*, legacy_blocked: bool) -> None:
    with tempfile.TemporaryDirectory(
        prefix="toad-goal-set-", dir="/var/tmp"
    ) as directory:
        root = Path(directory)
        os.environ["AGENT_COMMS_AGENT_MODELS"] = "openrouter/fake"
        comms = wire(root / "wire")
        project = root / "project"
        project.mkdir()
        owner = CommsAgent(
            comms,
            agent_bin="pi",
            agent_args=["--provider", "openrouter", "--model", "fake"],
            runtime_enabled=True,
            auto_wake=False,
        )
        session = (await owner.new_session(cwd=str(project))).session_id
        toad_agent = SimpleNamespace(
            _coordination_root=comms.root,
            _coordination_thread=session,
        )
        try:
            if legacy_blocked:
                old = comms.update_goal(session, "set", text="legacy goal")
                comms.update_goal(
                    session,
                    "blocked",
                    goal_id=old.id,
                    progress="Goal attempt unresolved",
                )
                assert not (
                    comms.root / "goal-private" / "goal_attempts.sqlite3"
                ).exists()
            goal = await Agent.update_goal(toad_agent, "set", "Finish the task")
            assert goal is not None and goal.status == "active"
            generation = GoalAttemptStore(comms.root / "goal-private").snapshot(goal.id)
            assert generation is not None and generation.state == "ready"
            assert owner._goal_store.ready_grant(goal.id, generation.number)
            assert comms.registry.require(session).goal == goal
        finally:
            await owner.shutdown()


async def main() -> None:
    await owner_set_route(legacy_blocked=False)
    await owner_set_route(legacy_blocked=True)
    print("goal set: fresh and legacy-blocked owner grants ready")


if __name__ == "__main__":
    asyncio.run(main())
