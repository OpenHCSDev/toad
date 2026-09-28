"""Toad goal editing/history use the actual runtime owner and preserve identity."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.acp import CommsAgent
from agent_comms.acp_extension import GoalChangedUpdate, decode_updates, encode_updates
from comms_boundary_fixture import attach_coordination
from runtime_fixture import private_native_wire

from toad.acp.agent import Agent
from toad.acp.messages import CommsUpdated


async def main():
    artifacts = Path(__file__).resolve().parents[1] / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="toad-goal-edit-owner-", dir=artifacts) as directory:
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
        try:
            session = (await owner.new_session(cwd=str(project))).session_id
            agent = Agent(
                project, {"name": "agent-comms", "run_command": {"*": "true"}}, None
            )
            attach_coordination(agent, str(comms.root), session)
            original = await agent.update_goal("set", "Original objective")
            changed = await agent.edit_goal(original, "Revised objective")
            assert changed.id == original.id
            assert changed.revision == original.revision + 1
            assert changed.state.declared_name == original.state.declared_name
            assert comms.registry.require(session).goal == changed
            try:
                await agent.edit_goal(original, "Stale overwrite")
            except ValueError:
                pass
            else:
                raise AssertionError("Owner accepted a stale goal edit")
            history = await agent.get_goal_history(changed.id)
            assert any(
                (
                    entry["after"] and entry["after"]["text"] == "Original objective"
                    for entry in history
                )
            )
            assert any(
                (
                    entry["before"]
                    and entry["before"]["text"] == "Original objective"
                    and (entry["after"]["text"] == "Revised objective")
                    for entry in history
                )
            )
            assert not any(
                (
                    entry["after"] and entry["after"]["text"] == "Stale overwrite"
                    for entry in history
                )
            )
            execution = await agent.get_goal_execution()
            assert execution.goal_id == changed.id
            assert await agent.get_goal_snapshot() == (changed, execution)
            emitted = []
            agent.post_message = emitted.append
            for fact in (
                GoalChangedUpdate(changed, execution),
                GoalChangedUpdate(None, None),
            ):
                agent.rpc_session_update(
                    session,
                    {
                        "sessionUpdate": "session_info_update",
                        "_meta": encode_updates(fact),
                    },
                )
                snapshot = next(
                    item.update
                    for item in reversed(emitted)
                    if isinstance(item, CommsUpdated)
                    and isinstance(item.update, GoalChangedUpdate)
                )
                assert snapshot == fact
            emitted.clear()
            for fact in decode_updates(owner.sessions.metadata(session)):
                agent.comms_consumer_class(agent, agent.session_id).dispatch_sync(fact)
            snapshot = next(
                item.update
                for item in emitted
                if isinstance(item, CommsUpdated)
                and isinstance(item.update, GoalChangedUpdate)
            )
            assert snapshot.goal == changed and snapshot.execution == execution

        finally:
            await owner.shutdown()
    print(
        "goal owner: actual RuntimeServer stable-ID edit, revision CAS, history and execution projection"
    )


if __name__ == "__main__":
    asyncio.run(main())
