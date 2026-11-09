"""Authored protocol controls derived from original registry/turn custody.

These controls acquire metadata leases, never a native input or MCP grant.
The external observer separately receives the actual native producer's updates.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any

from agent_comms.execution.acp import CommsAgent
from agent_comms.acp_extension import (
    McpClientAcknowledgementUpdate,
    TurnChangedUpdate,
    encode_updates,
)
from agent_comms.comms import wire
from agent_comms.coordination.coordinator import Coordination
from agent_comms.execution.launch_runtime import ThreadLaunch
from agent_comms.execution.pi_wire import McpLiveAcknowledgement, McpServerReceipt
from agent_comms.execution.turn_lease import NoFinishedTurn
from agent_comms.nominal.field_codec import AcpSessionId, FieldCodec, InputId, TurnId
from agent_comms.pi_payloads import ConfirmMcpCallPolicy, ReadyMcpServerState
from textual.pilot import Pilot

from toad.acp.agent import Agent
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation
from toad.widgets.note import Note

RETIRED = TurnId("0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a")
OBSERVED = TurnId("9f8e7d6c5b4a39281706f5e4d3c2b1a0")

RELAY = Path(__file__).resolve().parents[1] / "peers" / "relay.py"

# The relay's socket module sits beside the relay script, which imports it as a script. This
# adapter is loaded by file, so it reaches the same module the same way: from its directory.
sys.path.append(str(RELAY.parent))
from relay_socket import RelaySocket  # noqa: E402

AGENT_DATA = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
              "run_command": {"*": shlex.join((sys.executable, str(RELAY)))}, "protocol": "acp"}


def packet(*facts):
    return {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(*facts)}


def notes(view):
    return [str(widget.render()) for widget in view.contents.children
            if isinstance(widget, Note) and "MCP live" in str(widget.render())]


@asynccontextmanager
async def turn_source(wire_root: Path, project: Path, session_id: AcpSessionId):
    """Use the original declaration, attachment and retirement owners once."""
    # This authored owner has its own registry. Inherited public caller names
    # must not select a different participant during same-process retirement.
    previous = ThreadLaunch.inherited(os.environ)
    ThreadLaunch.strip(os.environ)
    try:
        async with AsyncExitStack() as resources:
            project.mkdir(parents=True, exist_ok=True)
            comms = await Coordination.run_worker(partial(wire, wire_root))
            producer = CommsAgent(comms, auto_wake=False)

            def declare():
                thread = producer.sessions.declare_thread(str(project))
                # Enlist cleanup before joined worker delivery, including a
                # cancelled declaration whose committed owner must retire.
                resources.push_async_callback(
                    Coordination.run_worker, partial(comms.owners.stop, thread.name),
                )
                return thread

            thread = await Coordination.run_worker(declare)
            # Retirement runs in reverse: the owner releases its own binding first, so the
            # stop retires a released declaration instead of dialing a still-bound owner.
            resources.push_async_callback(producer.shutdown)
            await producer.sessions.bind_owned(thread, session_id)
            yield producer
    finally:
        ThreadLaunch.strip(os.environ)
        os.environ.update(previous)


class Relay(RelaySocket):
    """The adapter's end of the relay peer Toad runs as its agent: every update and permission
    request goes to Toad over that peer's ACP pipe, as a real agent's would."""

    def __init__(self, port: int, view: Conversation, pilot: Pilot) -> None:
        super().__init__(port)
        self.view, self.pilot = view, pilot
        self.settled_count = 0

    @classmethod
    async def started(cls, project: Path, view: Conversation, pilot: Pilot) -> Relay:
        port_file = cls.port_file(project)
        async with asyncio.timeout(30):
            while not port_file.exists():
                await pilot.pause(.05)
        return cls(RelaySocket.published(project).port, view, pilot)

    async def update(self, update: dict[str, Any], session: str) -> None:
        await self.step({"update": update, "session": session})
        await self.settled()

    async def settled(self) -> None:
        """Toad handles a session's updates in order: once a marker said after them has
        arrived, everything sent before it has been handled."""
        self.settled_count += 1
        marker = f"RELAY_SETTLED_{self.settled_count}"
        await self.step({"say": marker})
        async with asyncio.timeout(10):
            while marker not in self.said():
                await self.pilot.pause(.02)

    def said(self) -> str:
        """What the agent has said, as its message bodies hold it: unwrapped, so a marker is
        found whatever the terminal width (the drawn screen wraps lines mid-marker)."""
        return "".join(response.body.get_clipboard_text() for response in self.view.query(AgentResponse))


@asynccontextmanager
async def exercise_boundaries(relay: Relay, agent: Agent, view: Conversation) -> AsyncIterator[None]:
    """Exercise the authored MCP boundaries, then keep their turn source open for the caller:
    the turn records Toad last saw live in it, so it outlives everything sent after them."""
    receipt = McpLiveAcknowledgement(1, "pi-mcp-client", InputId("a" * 32), "running", "turn", (
        McpServerReceipt("fixture", "project", ReadyMcpServerState,
                         ConfirmMcpCallPolicy, 1, 0, 0),
    ))

    async def send(*facts, session=None):
        await relay.update(packet(*facts), session or agent.session_id)

    session_id = FieldCodec.decode(AcpSessionId, agent.session_id)
    source_root = agent.project_root_path.parent / "mcp-boundaries"
    async with turn_source(source_root / "wire", source_root / "project", session_id) as producer:
        name = producer.sessions.require(session_id)
        async with AsyncExitStack() as custody:
            retired_owner = await Coordination.run_worker(partial(
                producer.turns.acquire_turn, custody, session_id, name,
                RETIRED, "Authored MCP boundary; no input",
            ))
            # The lease is read while the turn is held: closing this stack retires its file.
            retired_lease = retired_owner.turn_lease
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
            # Deliberate: Toad must refuse a session it does not hold. Its log then carries one
            # "ACP session is retired or unknown" (agent_process.py recipient); that line is
            # this boundary passing, not a fault.
            await send(McpClientAcknowledgementUpdate(OBSERVED, receipt), session="foreign")
            await send(McpClientAcknowledgementUpdate(RETIRED, receipt))
            assert not notes(view)
            malformed = packet(McpClientAcknowledgementUpdate(OBSERVED, receipt))
            malformed["_meta"]["agentComms"]["updates"][0]["receipt"]["version"] = True
            await relay.update(malformed, session_id)
            assert not notes(view)
            await send(McpClientAcknowledgementUpdate(OBSERVED, receipt))
            rendered = notes(view)
            assert len(rendered) == 1 and "not a grant" in rendered[0]
            await send(McpClientAcknowledgementUpdate(OBSERVED, receipt))
            assert notes(view) == rendered
            assert await Coordination.run_worker(partial(
                producer._comms.agents.finish_turn, retired_lease,
            )) == NoFinishedTurn()
            await send(TurnChangedUpdate(retired.state))
            assert agent.current_turn.managed_id == view.turns.managed_id == OBSERVED
        terminal = await Coordination.run_worker(partial(producer.turns.current_turn_update, session_id))
        await send(TurnChangedUpdate(terminal.state))
        assert agent.current_turn.managed_id is view.turns.managed_id is None
        assert not notes(view)
        await send(McpClientAcknowledgementUpdate(OBSERVED, receipt))
        assert not notes(view)
        yield
