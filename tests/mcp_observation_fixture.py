"""Typed receipt lifetime probes reused by the actual native MCP UI observer."""
from agent_comms.acp_extension import (
    McpClientReceiptUpdate, TurnStartedUpdate, TurnSettledUpdate, encode_updates,
)
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


async def exercise_boundaries(agent, view, pilot):
    receipt = McpLiveReceipt(1, "pi-mcp-client", "a" * 32, "running", "turn", (
        McpServerReceipt("fixture", "project", ReadyMcpServerState,
                         ConfirmMcpCallPolicy, 1, 0, 0),
    ))

    async def send(*facts, session=None):
        agent.rpc_session_update(session or agent.session_id, packet(*facts))
        await pilot.pause()

    await send(McpClientReceiptUpdate("retired", receipt))
    assert not notes(view)
    await send(TurnStartedUpdate("observed", None, None, None))
    assert agent._active_turn_id == view.turns.managed_id == "observed"
    await send(McpClientReceiptUpdate("observed", receipt), session="foreign")
    await send(McpClientReceiptUpdate("retired", receipt))
    assert not notes(view)
    malformed = packet(McpClientReceiptUpdate("observed", receipt))
    malformed["_meta"]["agentComms"]["updates"][0]["receipt"]["version"] = True
    agent.rpc_session_update(agent.session_id, malformed)
    await pilot.pause()
    assert not notes(view)
    await send(McpClientReceiptUpdate("observed", receipt))
    rendered = notes(view)
    assert len(rendered) == 1 and "not a grant" in rendered[0]
    await send(McpClientReceiptUpdate("observed", receipt))
    assert notes(view) == rendered
    await send(TurnSettledUpdate("retired"))
    assert agent._active_turn_id == view.turns.managed_id == "observed"
    await send(TurnSettledUpdate("observed"))
    assert agent._active_turn_id is view.turns.managed_id is view._mcp_live_turn is None
    assert not notes(view)
    await send(McpClientReceiptUpdate("observed", receipt))
    assert not notes(view)
