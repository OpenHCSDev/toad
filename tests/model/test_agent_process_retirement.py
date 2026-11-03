"""Real ACP handshake/EOF/cancellation retire the original process group."""

import asyncio
from collections.abc import Callable

import pytest
from acp import text_block
from acp.exceptions import RequestError

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
        runner, = agent.process.runner.tasks()
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


@pytest.mark.parametrize("close_refused", (False, True))
async def test_stopping_one_shared_session_keeps_the_other_usable(
    workspace: Workspace, close_refused: bool,
) -> None:
    definition = peer("shared_session", name="Shared sessions", identity="shared-sessions")
    first_name = "refuse-close" if close_refused else "first"
    first = workspace.agents.agent(Agent, definition, first_name)
    second = workspace.agents.agent(Agent, definition, "second")
    try:
        await first.start()
        await until(lambda: first.ready, "the first loaded session")
        process = first.process
        child = process.process
        assert child is not None
        await second.start(first.borrowed_processes())
        await until(lambda: second.ready, "the second loaded session")
        assert second.process is process
        if close_refused:
            with pytest.raises(RequestError) as refused:
                await first.stop()
            assert refused.value.code == -32602
            assert refused.value.data["details"] == "Original session close refused"
        else:
            await first.stop()
        assert not first.session.accepts_updates
        assert not first.session.responses
        assert second.ready and second.session.accepts_updates
        assert child.identity.alive()
        response = await second.process.rpc.prompt("second", [text_block("still-connected")])
        assert response is not None
        assert response.stop_reason == "end_turn"
        receipt = "close_refused" if close_refused else "closed"
        assert {row[receipt] for row in workspace.received() if receipt in row} == {first_name}
        assert any(row.get("prompt") == "still-connected" for row in workspace.received())
    finally:
        try:
            await first.stop()
        except RequestError:
            # Cleanup joins the same failed close; the original refusal was
            # asserted above and must not prevent releasing the second owner.
            if not close_refused:
                raise
        finally:
            await second.stop()
