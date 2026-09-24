"""Pinned agent-comms public types and ACP metadata used by Toad."""

import asyncio
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms import Comms, Goal, MessageRoute, TranscriptCursor, TranscriptPage, wire

from toad.acp.agent import Agent
from toad.acp.messages import CoordinationUpdate, Update


async def main() -> None:
    with TemporaryDirectory(prefix="toad-contract-") as directory:
        root = Path(directory)
        assert isinstance(wire(root / "wire"), Comms)
        assert all(
            isinstance(public_type, type)
            for public_type in (Comms, Goal, TranscriptCursor, TranscriptPage, MessageRoute)
        )
        with patch.dict("os.environ", {"TOAD_LOG": str(root / "agent.log")}):
            agent = Agent(root, {"name": "agent-comms", "run_command": {"*": "true"}}, None)

        sent = []
        agent.post_message = sent.append
        route = MessageRoute("worker", ("#team",))
        agent.rpc_session_update(
            "session",
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "routed reply"},
                "_meta": {"agentComms": {"route": asdict(route)}},
            },
        )
        assert len(sent) == 1 and isinstance(sent[0], Update)
        assert sent[0].route == route

        sent.clear()
        agent.rpc_session_update(
            "session",
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": ""},
                "_meta": {"agentComms": {
                    "thread": "worker", "wireRoot": str(root / "wire"),
                    "inputDisposition": {"status": "unknown", "sequence": 1},
                }},
            },
        )
        assert any(isinstance(message, CoordinationUpdate) for message in sent)
        assert not any(isinstance(message, Update) for message in sent)

        captured = []

        async def capture_prompt(blocks, metadata):
            captured.append((blocks, metadata))
            return "ok"

        agent.acp_session_prompt = capture_prompt
        assert await agent.send_prompt("hello", delivery="direct", defer_display=True) == "ok"
        assert captured[0][1] == {
            "agentComms": {"delivery": "direct", "deferDisplay": True, "userText": "hello"}
        }
        assert agent.prompt_in_flight == 0


if __name__ == "__main__":
    asyncio.run(main())
