from runtime_fixture import coordination_update
"""The Toad pause action records durable owner intent, not a model pause."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.comms import wire
from runtime_fixture import private_native_wire
from agent_comms.acp import CommsAgent

from toad.acp.agent import Agent


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-goal-pause-owner-", dir="/var/tmp") as directory:
        root = Path(directory)
        comms = private_native_wire(root / "wire")
        os.environ["AGENT_COMMS_AGENT_MODELS"] = "openrouter/fake"
        owner = CommsAgent(
            comms, agent_bin="pi", agent_args=["--provider", "openrouter", "--model", "fake"],
            runtime_enabled=True, auto_wake=False,
            private_nk_native_package=Path(os.environ["AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE"]),
            private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"],
        )
        try:
            session = (await owner.new_session(cwd=str(root))).session_id
            client = Agent(root, {"name": "agent-comms", "run_command": {"*": "true"}}, None)
            client.coordination = coordination_update(str(comms.root), session)
            goal = await client.update_goal("set", "Keep investigating until stopped")
            paused = await client.update_goal("paused")
            assert paused.id == goal.id and paused.state.declared_name == "paused"
            reopened = wire(comms.root)
            assert reopened.registry.require(session).goal == paused
            assert reopened.goals.goal_pause(session).source.declared_name == "owner"
            resumed = await client.update_goal("active")
            assert resumed.state.active and reopened.goals.goal_pause(session) is None
        finally:
            await owner.shutdown()
    print("goal pause: Toad owner intent survives reopen and explicit resume clears it")


if __name__ == "__main__":
    asyncio.run(main())
