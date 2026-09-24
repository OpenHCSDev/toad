"""Pinned agent-comms public types and ACP metadata used by Toad."""

import asyncio
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import quote

from agent_comms import Comms, Goal, MessageRoute, TranscriptCursor, TranscriptPage, wire

from toad.acp.agent import Agent
from toad.acp.messages import CoordinationUpdate, Update
from toad.conversation_markdown import _path_parser


async def main() -> None:
    with TemporaryDirectory(prefix="toad-contract-") as directory:
        root = Path(directory)
        assert isinstance(wire(root / "wire"), Comms)
        assert all(
            isinstance(public_type, type)
            for public_type in (Comms, Goal, TranscriptCursor, TranscriptPage, MessageRoute)
        )
        log_file = root / "agent log.txt"
        with patch.dict("os.environ", {"TOAD_LOG": str(log_file)}):
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
                "content": {"type": "text", "text": "[agent error] Pi preflight failed."},
            },
        )
        assert len(sent) == 1 and isinstance(sent[0], Update)
        log_file.write_text("ACP diagnostics\n")
        links = [
            child.attrs.get("href")
            for token in _path_parser(root).parse(sent[0].text)
            for child in (token.children or [])
            if child.type == "link_open"
        ]
        assert links == [f"toad-file:{quote(str(log_file))}"]

        sent.clear()
        agent.rpc_session_update(
            "session",
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "normal reply"},
            },
        )
        assert len(sent) == 1 and sent[0].text == "normal reply"

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
