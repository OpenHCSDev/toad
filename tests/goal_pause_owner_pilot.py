"""The Toad pause action records durable owner intent, not a model pause."""

import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace

from agent_comms import Thread, wire
from toad.acp.agent import Agent


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-goal-pause-owner-", dir="/var/tmp") as directory:
        root = Path(directory)
        comms = wire(root / "wire")
        comms.register(Thread("worker", frozenset(), str(root)))
        goal = comms.update_goal("worker", "set", text="Keep investigating until stopped")
        client = SimpleNamespace(_coordination_root=comms.root, _coordination_thread="worker")
        paused = await Agent.update_goal(client, "paused")
        assert paused.id == goal.id and paused.status == "paused"
        reopened = wire(comms.root).registry.require("worker").goal
        assert reopened.paused_by == "owner"
        assert reopened.owner_pause_instruction is not None
        resumed = await Agent.update_goal(client, "active")
        assert resumed.active and resumed.paused_by is None
    print("goal pause: Toad owner intent survives reopen and explicit resume clears it")


if __name__ == "__main__":
    asyncio.run(main())
