"""The relay peer is an ordinary ACP agent to Toad, whose steps arrive live from outside the pipe:
a step sent on its socket reaches Toad over stdio, an ask's outcome comes back on the socket,
and a step Toad refuses comes back as Toad's error."""
import asyncio

import pytest

from toad.launch_binding import AgentAttached

from support.agents import peer
from support.peers.relay_socket import RelaySocket, RelayStepFailed


async def test_relayed_steps_reach_toad_and_an_ask_answers_back(workspace):
    async with workspace.app(size=(110, 40), binding=AgentAttached(peer("relay"))) as ui:
        await ui.until_agent_ready()
        relay = RelaySocket.published(workspace.project)
        await relay.step({"say": "RELAYED_FROM_OUTSIDE"})
        await ui.until_shows("RELAYED_FROM_OUTSIDE")
        asked = asyncio.ensure_future(relay.step({"permission": {
            "toolCall": {"toolCallId": "relay-call", "title": "RELAYED_PERMISSION", "kind": "other",
                         "content": [{"type": "content",
                                      "content": {"type": "text", "text": "RELAYED_PREVIEW"}}]},
            "options": [{"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "no", "name": "Reject", "kind": "reject_once"}]}}))
        await ui.until_shows("RELAYED_PERMISSION")
        await ui.until_shows("a Allow")
        await ui.until_shows("RELAYED_PREVIEW")
        await ui.press("a")
        await ui.until(asked.done, why="the outcome back on the relay socket")
        assert asked.result() == {"outcome": {"outcome": "selected", "optionId": "yes"}}
        with pytest.raises(RelayStepFailed, match="ACP session is retired or unknown"):
            await relay.step({"ask": "FOREIGN_ASK", "session": "foreign"})
