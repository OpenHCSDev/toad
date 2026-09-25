"""Toad goal editing/history use the actual runtime owner and preserve identity."""

import asyncio
import os
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.acp import CommsAgent
from agent_comms.operations import wire

from toad.acp.agent import Agent
from toad.acp.messages import GoalSnapshotUpdate


async def main():
    with TemporaryDirectory(
        prefix="toad-goal-edit-owner-", dir="/var/tmp"
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
        try:
            session = (await owner.new_session(cwd=str(project))).session_id
            agent = Agent(
                project, {"name": "agent-comms", "run_command": {"*": "true"}}, None
            )
            agent._coordination_root = str(comms.root)
            agent._coordination_thread = session
            original = await agent.update_goal("set", "Original objective")
            changed = await agent.edit_goal(original, "Revised objective")
            assert changed.id == original.id
            assert changed.revision == original.revision + 1
            assert changed.status == original.status
            assert comms.registry.require(session).goal == changed
            try:
                await agent.edit_goal(original, "Stale overwrite")
            except ValueError:
                pass
            else:
                raise AssertionError("Owner accepted a stale goal edit")
            history = await agent.get_goal_history(changed.id)
            assert any(
                entry["after"] and entry["after"]["text"] == "Original objective"
                for entry in history
            )
            assert any(
                entry["before"]
                and entry["before"]["text"] == "Original objective"
                and entry["after"]["text"] == "Revised objective"
                for entry in history
            )
            assert not any(
                entry["after"] and entry["after"]["text"] == "Stale overwrite"
                for entry in history
            )
            execution = await agent.get_goal_execution()
            assert execution.goal_id == changed.id
            assert await agent.get_goal_snapshot() == (changed, execution)
            emitted = []
            agent.post_message = emitted.append
            for goal_value, execution_value in (
                (asdict(changed), asdict(execution)),
                (None, None),
            ):
                agent.rpc_session_update(
                    session,
                    {
                        "sessionUpdate": "session_info_update",
                        "_meta": {
                            "agentComms": {
                                "goal": goal_value,
                                "goalExecution": execution_value,
                            }
                        },
                    },
                )
                snapshot = next(
                    item
                    for item in reversed(emitted)
                    if isinstance(item, GoalSnapshotUpdate)
                )
                assert snapshot.goal == (changed if goal_value else None)
                assert snapshot.execution == (execution if execution_value else None)
            emitted.clear()
            agent._publish_coordination_metadata(
                {"_meta": owner._session_metadata(session)}, initial=True
            )
            snapshot = next(
                item for item in emitted if isinstance(item, GoalSnapshotUpdate)
            )
            assert snapshot.goal == changed and snapshot.execution == execution
        finally:
            await owner.shutdown()
    print(
        "goal owner: actual RuntimeServer stable-ID edit, revision CAS, history and execution projection"
    )


if __name__ == "__main__":
    asyncio.run(main())
