"""The Toad pause action records durable owner intent, not a model pause."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import wire
from agent_comms.acp import CommsAgent

from toad.acp.agent import Agent


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-goal-pause-owner-", dir="/var/tmp") as directory:
        root = Path(directory)
        comms = wire(root / "wire")
        os.environ["AGENT_COMMS_AGENT_MODELS"] = "openrouter/fake"
        owner = CommsAgent(
            comms, agent_bin="pi", agent_args=["--provider", "openrouter", "--model", "fake"],
            runtime_enabled=True, auto_wake=False,
        )
        try:
            session = (await owner.new_session(cwd=str(root))).session_id
            client = Agent(root, {"name": "agent-comms", "run_command": {"*": "true"}}, None)
            client._coordination_root = str(comms.root)
            client._coordination_thread = session
            goal = await client.update_goal("set", "Keep investigating until stopped")
            paused = await client.update_goal("paused")
            assert paused.id == goal.id and paused.status == "paused"
            reopened = wire(comms.root)
            assert reopened.registry.require(session).goal == paused
            assert reopened.goal_pause(session).source == "owner"
            resumed = await client.update_goal("active")
            assert resumed.active and reopened.goal_pause(session) is None
        finally:
            await owner.shutdown()
    print("goal pause: Toad owner intent survives reopen and explicit resume clears it")


if __name__ == "__main__":
    asyncio.run(main())
