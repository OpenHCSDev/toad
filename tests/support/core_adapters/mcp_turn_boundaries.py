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
    McpClientAcknowledgementUpdate, TurnChangedUpdate, encode_updates,
)
from agent_comms.comms import wire
from agent_comms.coordinator import Coordination
from agent_comms.field_codec import TurnId
from agent_comms.launch_runtime import ThreadLaunch
from agent_comms.pi_payloads import (
    McpLiveAcknowledgement, McpServerReceipt, ReadyMcpServerState, ConfirmMcpCallPolicy,
)
from toad.widgets.note import Note

RETIRED = TurnId("0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a")
OBSERVED = TurnId("9f8e7d6c5b4a39281706f5e4d3c2b1a0")

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
    previous = ThreadLaunch.inherited(os.environ)
    ThreadLaunch.strip(os.environ)
    try:
        async with AsyncExitStack() as resources:
            project = root / "project"
            project.mkdir(parents=True, exist_ok=True)
            comms = await Coordination.run_worker(partial(wire, root / "wire"))
            producer = CommsAgent(comms, runtime_enabled=False, auto_wake=False)
            resources.push_async_callback(producer.shutdown)

            def declare():
                thread = producer.sessions.declare_thread(str(project))
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
        ThreadLaunch.strip(os.environ)
        os.environ.update(previous)


async def exercise_boundaries(agent, view, pilot):
    receipt = McpLiveAcknowledgement(1, "pi-mcp-client", "a" * 32, "running", "turn", (
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
                RETIRED, "Authored MCP boundary; no input",
            ))
        retired = await Coordination.run_worker(partial(producer.turns.current_turn_update, session_id))
        await send(McpClientAcknowledgementUpdate(RETIRED, receipt))
        assert not notes(view)
        async with AsyncExitStack() as custody:
            await Coordination.run_worker(partial(
                producer.turns.acquire_turn, custody, session_id, name,
                OBSERVED, "Authored MCP boundary; no input",
            ))
            active = await Coordination.run_worker(partial(producer.turns.current_turn_update, session_id))
            await send(TurnChangedUpdate(active.state))
            assert agent.current_turn.managed_id == view.turns.managed_id == OBSERVED
            await send(McpClientAcknowledgementUpdate(OBSERVED, receipt), session="foreign")
            await send(McpClientAcknowledgementUpdate(RETIRED, receipt))
            assert not notes(view)
            malformed = packet(McpClientAcknowledgementUpdate(OBSERVED, receipt))
            malformed["_meta"]["agentComms"]["updates"][0]["receipt"]["version"] = True
            result = await agent.server.call({
                "jsonrpc": "2.0", "method": "session/update", "params": {
                    "sessionId": session_id, "update": malformed,
                },
            })
            assert result is None, result
            await pilot.pause()
            assert not notes(view)
            await send(McpClientAcknowledgementUpdate(OBSERVED, receipt))
            rendered = notes(view)
            assert len(rendered) == 1 and "not a grant" in rendered[0]
            await send(McpClientAcknowledgementUpdate(OBSERVED, receipt))
            assert notes(view) == rendered
            assert await Coordination.run_worker(partial(
                producer._comms.agents.finish_turn, retired_owner.turn_lease,
            )) is None
            await send(TurnChangedUpdate(retired.state))
            assert agent.current_turn.managed_id == view.turns.managed_id == OBSERVED
        terminal = await Coordination.run_worker(partial(producer.turns.current_turn_update, session_id))
        await send(TurnChangedUpdate(terminal.state))
        assert agent.current_turn.managed_id is view.turns.managed_id is None
        assert not notes(view)
        await send(McpClientAcknowledgementUpdate(OBSERVED, receipt))
        assert not notes(view)
