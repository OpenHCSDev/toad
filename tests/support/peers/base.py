"""A scripted ACP agent: the official SDK over stdio, no model and no provider.

It records what it receives in ``peer-received.jsonl`` in the project, which is
where ``Workspace.received`` reads it. Subclasses change what it answers.
"""

import asyncio
import json
from pathlib import Path

from acp import Agent, Client, run_agent
from acp.schema import (
    AgentMessageChunk, InitializeResponse, NewSessionResponse, PromptResponse, TextContentBlock,
)

RECEIVED = "peer-received.jsonl"


class Peer(Agent):
    session_id = "peer-session"

    def on_connect(self, conn: Client) -> None:
        self.connection = conn

    async def initialize(self, protocol_version: int, **kwargs):
        return InitializeResponse(protocolVersion=protocol_version)

    async def new_session(self, cwd: str, **kwargs):
        self.project = Path(cwd)
        return NewSessionResponse(sessionId=self.session_id)

    async def prompt(self, session_id, prompt, **kwargs):
        text = prompt[0].text
        self.record(prompt=text)
        await self.answer(session_id, text)
        return PromptResponse(stopReason="end_turn")

    async def answer(self, session_id: str, text: str) -> None:
        await self.say(session_id, f"PEER_ANSWER {text}")

    async def say(self, session_id: str, text: str) -> None:
        await self.connection.session_update(session_id=session_id, update=AgentMessageChunk(
            sessionUpdate="agent_message_chunk", content=TextContentBlock(type="text", text=text)))

    def record(self, **fact) -> None:
        with (self.project / RECEIVED).open("a") as stream:
            stream.write(json.dumps(fact) + "\n")

    @classmethod
    def main(cls) -> None:
        asyncio.run(run_agent(cls()))
