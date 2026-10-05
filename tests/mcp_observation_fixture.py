"""Authored protocol controls derived from original registry/turn custody.

These controls acquire metadata leases, never a native input or MCP grant.
The external observer separately receives the actual native producer's updates.
"""
from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
import os
from pathlib import Path

from agent_comms.acp import CommsAgent
from agent_comms.acp_extension import (
    McpClientReceiptUpdate, TurnChangedUpdate, encode_updates,
)
from agent_comms.comms import wire
from agent_comms.coordinator import Coordination
from agent_comms.pi_payloads import (
    McpLiveReceipt, McpServerReceipt, ReadyMcpServerState, ConfirmMcpCallPolicy,
)
from toad.widgets.note import Note

AGENT_DATA = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
              "run_command": {"*": "true"}, "protocol": "acp"}


def packet(*facts):
    return {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(*facts)}


def notes(view):
    return [str(widget.render()) for widget in view.contents.children
            if isinstance(widget, Note) and "MCP live" in str(widget.render())]


@asynccontextmanager
async def turn_source(root: Path, session_id: str):
    """Use the original declaration, attachment and retirement owners once."""
    # This authored owner has its own registry. Inherited public caller names
    # must not select a different participant during same-process retirement.
    caller_keys = ("PI_AGENT_ID", "AGENT_COMMS_THREAD")
    previous = {key: os.environ.pop(key, None) for key in caller_keys}
    try:
        async with AsyncExitStack() as resources:
            project = root / "project"
            project.mkdir(parents=True, exist_ok=True)
            comms = await Coordination.run_worker(partial(wire, root / "wire"))
            producer = CommsAgent(comms, runtime_enabled=False, auto_wake=False)
            resources.push_async_callback(producer.shutdown)

            def declare():
                thread = producer.sessions.declare_thread(str(project), os.getpid())
                # Enlist cleanup before joined worker delivery, including a
                # cancelled declaration whose committed owner must retire.
                resources.push_async_callback(
                    Coordination.run_worker, partial(comms.owners.stop, thread.name),
                )
                return thread

            thread = await Coordination.run_worker(declare)
            await producer.sessions.bind_owned(thread, session_id)
            yield producer
    finally:
        for key, value in previous.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)


async def exercise_boundaries(agent, view, pilot):
    receipt = McpLiveReceipt(1, "pi-mcp-client", "a" * 32, "running", "turn", (
        McpServerReceipt("fixture", "project", ReadyMcpServerState,
                         ConfirmMcpCallPolicy, 1, 0, 0),
    ))

    async def send(*facts, session=None):
        result = await agent.server.call({
            "jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": session or agent.session_id, "update": packet(*facts),
            },
        })
        assert result is None, result
        await pilot.pause()

    session_id = agent.session_id
    source_root = agent.project_root_path.parent / "mcp-boundaries"
    async with turn_source(source_root, session_id) as producer:
        name = producer.sessions.require(session_id)
        async with AsyncExitStack() as custody:
            retired_owner = await Coordination.run_worker(partial(
                producer.turns.acquire_turn, custody, session_id, name,
                "retired", "Authored MCP boundary; no input",
            ))
        retired = await Coordination.run_worker(partial(producer.turns.current_turn_update, session_id))
        await send(McpClientReceiptUpdate(retired.state.finished_turn_id, receipt))
        assert not notes(view)
        async with AsyncExitStack() as custody:
            await Coordination.run_worker(partial(
                producer.turns.acquire_turn, custody, session_id, name,
                "observed", "Authored MCP boundary; no input",
            ))
            active = await Coordination.run_worker(partial(producer.turns.current_turn_update, session_id))
            turn_id = active.state.managed_id
            await send(TurnChangedUpdate(active.state))
            assert agent.current_turn.managed_id == view.turns.managed_id == turn_id
            await send(McpClientReceiptUpdate(turn_id, receipt), session="foreign")
            await send(McpClientReceiptUpdate(retired.state.finished_turn_id, receipt))
            assert not notes(view)
            malformed = packet(McpClientReceiptUpdate(turn_id, receipt))
            malformed["_meta"]["agentComms"]["updates"][0]["receipt"]["version"] = True
            result = await agent.server.call({
                "jsonrpc": "2.0", "method": "session/update", "params": {
                    "sessionId": session_id, "update": malformed,
                },
            })
            assert result is None, result
            await pilot.pause()
            assert not notes(view)
            await send(McpClientReceiptUpdate(turn_id, receipt))
            rendered = notes(view)
            assert len(rendered) == 1 and "not a grant" in rendered[0]
            await send(McpClientReceiptUpdate(turn_id, receipt))
            assert notes(view) == rendered
            assert await Coordination.run_worker(partial(
                producer._comms.agents.finish_turn, retired_owner.turn_lease,
            )) is None
            await send(TurnChangedUpdate(retired.state))
            assert agent.current_turn.managed_id == view.turns.managed_id == turn_id
        terminal = await Coordination.run_worker(partial(producer.turns.current_turn_update, session_id))
        await send(TurnChangedUpdate(terminal.state))
        assert agent.current_turn.managed_id is view.turns.managed_id is None
        assert not notes(view)
        await send(McpClientReceiptUpdate(turn_id, receipt))
        assert not notes(view)
