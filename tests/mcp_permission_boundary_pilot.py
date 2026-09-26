"""Provider-free generic ACP permission-boundary pilot (no MCP policy in Toad)."""

import asyncio
import os
import tempfile
from pathlib import Path

from toad.acp import agent as agent_module
from typing import cast

from textual.message import Message

from toad.acp.agent import Agent
from toad.acp.messages import McpClientStopped, RequestPermission
from toad.agent_schema import Agent as AgentData
from toad.answer import Answer


class PermissionAgent(Agent):
    def __init__(self, root: Path):
        super().__init__(root, cast(AgentData, {
            "name": "Fixture", "identity": "fixture", "short_name": "fixture",
            "run_command": {"*": "true"}, "protocol": "acp",
        }), "owned-session")
        self.posted: list[RequestPermission] = []
        self.accepting = True

    def post_message(self, message: Message) -> bool:
        if not self.accepting:
            return False
        if isinstance(message, McpClientStopped):
            return True
        assert isinstance(message, RequestPermission)
        self.posted.append(message)
        return True


CANCELLED = {"outcome": {"outcome": "cancelled"}}
OPTIONS = [
    {"name": "Allow once", "optionId": "allow", "kind": "allow_once"},
    {"name": "Deny", "optionId": "deny", "kind": "reject_once"},
]
TOOL = {"toolCallId": "remote-tool-1", "title": "Generic tool request"}


async def verify(root: Path) -> None:
    agent = PermissionAgent(root)
    posted = agent.posted

    # Never show an ask from another session or answer one after session change.
    assert await agent.rpc_request_permission("wrong-session", OPTIONS, TOOL) == CANCELLED
    assert not posted
    pending = asyncio.create_task(agent.rpc_request_permission("owned-session", OPTIONS, TOOL))
    await asyncio.sleep(0)
    assert len(posted) == 1 and not pending.done()
    agent.session_id = "replacement-session"
    posted[-1].result_future.set_result(Answer("Allow once", "allow", "allow_once"))
    assert await pending == CANCELLED
    agent.session_id = "owned-session"

    # An absent controller must be denied immediately, not left waiting on a UI Future.
    agent.accepting = False
    denied_tool = {"toolCallId": "unseen-tool", "title": "Unseen request"}
    assert await agent.rpc_request_permission("owned-session", OPTIONS, denied_tool) == CANCELLED
    assert "unseen-tool" not in agent.tool_calls
    assert not agent._pending_permission_answers

    # A current controller can select only an option actually offered by the agent.
    agent.accepting = True
    pending = asyncio.create_task(agent.rpc_request_permission("owned-session", OPTIONS, TOOL))
    await asyncio.sleep(0)
    posted[-1].result_future.set_result(Answer("Forged", "not-offered", "allow_once"))
    assert await pending == CANCELLED
    pending = asyncio.create_task(agent.rpc_request_permission("owned-session", OPTIONS, TOOL))
    await asyncio.sleep(0)
    posted[-1].result_future.set_result(Answer("Allow once", "allow", "allow_once"))
    assert await pending == {"outcome": {"optionId": "allow", "outcome": "selected"}}

    previous = agent_module.PERMISSION_TIMEOUT_SECONDS
    agent_module.PERMISSION_TIMEOUT_SECONDS = 0.01
    try:
        pending = asyncio.create_task(agent.rpc_request_permission("owned-session", OPTIONS, TOOL))
        await asyncio.sleep(0)
        timeout_future = posted[-1].result_future
        assert await pending == CANCELLED
        assert timeout_future.done() and not agent._pending_permission_answers
    finally:
        agent_module.PERMISSION_TIMEOUT_SECONDS = previous

    # Stop terminates a still-mounted question before closing the ACP process.
    pending = asyncio.create_task(agent.rpc_request_permission("owned-session", OPTIONS, TOOL))
    await asyncio.sleep(0)
    assert len(agent._pending_permission_answers) == 1
    await agent.stop()
    assert await pending == CANCELLED
    assert not agent._pending_permission_answers
    assert await agent.rpc_request_permission("owned-session", OPTIONS, TOOL) == CANCELLED


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-mcp-permission-boundary-") as directory:
        prior = os.environ.get("TOAD_LOG")
        os.environ["TOAD_LOG"] = str(Path(directory) / "agent.log")
        try:
            await verify(Path(directory))
        finally:
            if prior is None:
                os.environ.pop("TOAD_LOG", None)
            else:
                os.environ["TOAD_LOG"] = prior
    print("Generic ACP permissions: exact session, controller, option, timeout and stop fences pass")


if __name__ == "__main__":
    asyncio.run(main())
