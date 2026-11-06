"""The relay peer is an ordinary ACP agent to Toad, whose steps arrive live from outside the pipe:
a step sent on its socket reaches Toad over stdio, and an ask's outcome comes back on the socket."""
import asyncio
import json

from toad.session_scope import AgentAttached

from support.agents import peer


async def relay_step(workspace, raw: dict) -> dict:
    port = int((workspace.project / "peer-relay.port").read_text())
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(json.dumps(raw).encode() + b"\n")
        await writer.drain()
        return json.loads(await reader.readline())
    finally:
        writer.close()


async def test_relayed_steps_reach_toad_and_an_ask_answers_back(workspace):
    async with workspace.app(size=(110, 40), binding=AgentAttached(peer("relay"))) as ui:
        await ui.until_agent_ready()
        await relay_step(workspace, {"say": "RELAYED_FROM_OUTSIDE"})
        await ui.until_shows("RELAYED_FROM_OUTSIDE")
        asked = asyncio.ensure_future(relay_step(workspace, {"permission": {
            "toolCall": {"toolCallId": "relay-call", "title": "RELAYED_PERMISSION", "kind": "other"},
            "options": [{"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "no", "name": "Reject", "kind": "reject_once"}]}}))
        await ui.until_shows("RELAYED_PERMISSION")
        await ui.until_shows("a Allow")
        await ui.press("a")
        await ui.until(asked.done, why="the outcome back on the relay socket")
        assert asked.result() == {"outcome": {"outcome": "selected", "optionId": "yes"}}
