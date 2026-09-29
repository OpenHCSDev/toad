"""Physical official-SDK peer for delayed first session load; no Node/provider."""
import asyncio
import json
import os
from pathlib import Path
from acp import Agent, Client, run_agent
from acp.schema import (AgentCapabilities, AgentMessageChunk, InitializeResponse,
                        LoadSessionResponse, NewSessionResponse, PromptResponse,
                        TextContentBlock)
from agent_comms.acp_extension import CoordinationChangedUpdate, TranscriptSnapshotUpdate, encode_updates
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage


class NavigationPeer(Agent):
    def on_connect(self, conn: Client):
        self.connection = conn

    async def initialize(self, protocol_version, **kwargs):
        return InitializeResponse(protocolVersion=protocol_version,
                                  agentCapabilities=AgentCapabilities(loadSession=True))

    async def new_session(self, cwd, **kwargs):
        return NewSessionResponse(sessionId="owner")

    async def load_session(self, session_id, cwd, **kwargs):
        root = Path(cwd)
        if session_id != "owner":
            (root / ("load-entered-" + session_id)).touch()
            async with asyncio.timeout(15):
                while not (root / ("allow-" + session_id)).exists():
                    await asyncio.sleep(.02)
        cursor = TranscriptCursor("physical-sdk-" + session_id, 0)
        page = TranscriptPage((AssistantTranscript("SAVED_FIRST_OPEN_" + session_id),),
                              cursor, TranscriptCursor(cursor.session_file, 1), False, False)
        await self.connection.session_update(session_id=session_id,
            update=AgentMessageChunk(sessionUpdate="agent_message_chunk",
                content=TextContentBlock(type="text", text=""),
                field_meta=encode_updates(TranscriptSnapshotUpdate(page),
                    CoordinationChangedUpdate(ThreadIncarnation(session_id, 1.0),
                        os.environ["AGENT_COMMS_ROOT"], os.getpid(), cwd, None, None,
                        session_id, None))))
        return LoadSessionResponse()

    async def prompt(self, session_id, prompt, **kwargs):
        with (Path(os.environ["NAVIGATION_PEER_ROOT"]) / "sdk-inputs.jsonl").open("a") as out:
            out.write(json.dumps({"session": session_id, "text": prompt[0].text}) + "\n")
        await self.connection.session_update(session_id=session_id,
            update=AgentMessageChunk(sessionUpdate="agent_message_chunk",
                content=TextContentBlock(type="text", text="ONE_ANSWER_" + prompt[0].text)))
        return PromptResponse(stopReason="end_turn")


if __name__ == "__main__":
    asyncio.run(run_agent(NavigationPeer()))
