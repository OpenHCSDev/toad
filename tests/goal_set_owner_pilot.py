from runtime_fixture import coordination_update
"""The Toad Set Goal action must create the owner's private launch authority."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.acp import CommsAgent
from agent_comms.goal_attempts import GoalAttemptStore
from comms_boundary_fixture import attach_coordination
from runtime_fixture import private_native_wire

from toad.acp.agent import Agent


async def owner_set_route() -> None:
    with tempfile.TemporaryDirectory(
        prefix="toad-goal-set-", dir="/var/tmp"
    ) as directory:
        root = Path(directory)
        os.environ["AGENT_COMMS_AGENT_MODELS"] = "openrouter/fake"
        comms = private_native_wire(root / "wire")
        project = root / "project"
        project.mkdir()
        owner = CommsAgent(
            comms,
            agent_bin="pi",
            agent_args=["--provider", "openrouter", "--model", "fake"],
            runtime_enabled=True,
            auto_wake=False,
            private_nk_native_package=Path(
                os.environ["AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE"]
            ),
            private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"],
        )
        session = (await owner.new_session(cwd=str(project))).session_id
        toad_agent = Agent(project, {"name": "agent-comms", "run_command": {"*": "true"}}, None)
        toad_agent.coordination = coordination_update(str(comms.root), session)
        try:
            goal = await Agent.update_goal(toad_agent, "set", "Finish the task")
            assert goal is not None and goal.state.declared_name == "active"
            assert goal.text == "Finish the task"
            generation = GoalAttemptStore(comms.root / "goal-private").snapshot(goal.id)
            assert generation is not None and generation.lifecycle.ready
            assert owner.turns.goal_store.ready_grant(goal.id, generation.number)
            assert comms.registry.require(session).goal == goal
        finally:
            await owner.shutdown()


async def main() -> None:
    await owner_set_route()
    print("goal set: current private owner grant ready")


if __name__ == "__main__":
    asyncio.run(main())
