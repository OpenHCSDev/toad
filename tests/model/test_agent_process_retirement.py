"""Real ACP handshake/EOF/cancellation retire the original process group."""

import asyncio
from collections.abc import Callable

import pytest
from acp import text_block

from agent_comms.child_process import ProcessIdentity
from agent_comms.nominal.field_codec import FieldCodec
from support.agents import peer
from support.workspace import Workspace
from toad.acp.agent import Agent


async def until(condition: Callable[[], bool], why: str) -> None:
    try:
        async with asyncio.timeout(8):
            while not condition():
                await asyncio.sleep(.02)
    except TimeoutError:
        raise AssertionError(f"{why} not reached in 8s") from None


@pytest.mark.parametrize("how", ("cancel", "stop", "eof"))
async def test_the_child_and_session_are_retired(workspace: Workspace, how: str) -> None:
    agent = workspace.agents.agent(Agent, peer(
        "retirement_eof" if how == "eof" else "retirement",
        name="Retirement", identity="retirement",
    ))
    try:
        await agent.start()
        runner = agent.process.runner
        assert runner is not None
        await until(lambda: bool(workspace.received()), "the actual descendant receipt")
        descendant = FieldCodec.decode(ProcessIdentity, workspace.received()[0]["descendant"])
        if how != "eof":
            await until(lambda: agent.ready, "the actual SDK handshake")
            if how == "cancel":
                runner.cancel()
            else:
                await agent.stop()
        await asyncio.gather(runner, return_exceptions=True)
        await until(lambda: not descendant.alive(), "the original descendant birth to retire")
        assert not agent.session.accepts_updates
        assert not agent.session.responses
    finally:
        await agent.stop()


async def test_stopping_one_shared_session_keeps_the_other_usable(workspace: Workspace) -> None:
    definition = peer("shared_session", name="Shared sessions", identity="shared-sessions")
    first = workspace.agents.agent(Agent, definition, "first")
    second = workspace.agents.agent(Agent, definition, "second")
    try:
        await first.start()
        await until(lambda: first.ready, "the first loaded session")
        process = first.process
        child = process.process
        assert child is not None
        await second.start(first.borrowed_processes)
        await until(lambda: second.ready, "the second loaded session")
        assert second.process is process
        await first.stop()
        assert not first.session.accepts_updates
        assert not first.session.responses
        assert second.ready and second.session.accepts_updates
        assert child.identity.alive()
        response = await second.process.rpc.prompt("second", [text_block("still-connected")])
        assert response is not None
        assert response.stop_reason == "end_turn"
        assert {row["closed"] for row in workspace.received() if "closed" in row} == {"first"}
        assert any(row.get("prompt") == "still-connected" for row in workspace.received())
    finally:
        try:
            await first.stop()
        finally:
            await second.stop()
