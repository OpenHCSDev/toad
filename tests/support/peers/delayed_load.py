"""An ACP agent whose session load waits for the test, then publishes saved history through Core.

Loading session ``owner`` returns at once. Loading any other session touches ``load-entered-<id>`` in
the project and waits until the test releases ``load-<id>`` (``Workspace.release``); it then writes a
one-answer session file, records it on the thread and publishes the transcript page.
"""

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path

from acp.schema import (
    AgentCapabilities, AgentMessageChunk, InitializeResponse, LoadSessionResponse, NewSessionResponse,
    TextContentBlock,
)
from agent_comms.acp_extension import CoordinationChangedUpdate, TranscriptSnapshotUpdate, encode_updates

from base import Peer


class DelayedLoadPeer(Peer):
    session_id = "owner"

    async def initialize(self, protocol_version, **kwargs):
        return InitializeResponse(protocolVersion=protocol_version,
                                  agentCapabilities=AgentCapabilities(loadSession=True))

    async def new_session(self, cwd, **kwargs):
        self.project = Path(cwd)
        return NewSessionResponse(sessionId=self.session_id)

    async def load_session(self, session_id, cwd, **kwargs):
        from agent_comms.comms import wire

        self.project = Path(cwd)
        if session_id != self.session_id:
            (self.project / f"load-entered-{session_id}").touch()
            async with asyncio.timeout(15):
                while not (self.project / f"released-load-{session_id}").exists():
                    await asyncio.sleep(.02)
        root = os.environ["AGENT_COMMS_ROOT"]
        comms = wire(root)
        saved = self.project / f"sdk-history-{session_id}.jsonl"
        saved.write_text(json.dumps({"type": "message", "id": "saved-first-open", "message": {
            "role": "assistant", "content": [{"type": "text", "text": f"SAVED_FIRST_OPEN_{session_id}"}]}}) + "\n")
        comms.registry.declare(replace(comms.registry.require(session_id), session_file=str(saved)))
        read = comms.transcripts.capture_page_read(session_id)
        page = read.read()
        await self.connection.session_update(session_id=session_id, update=AgentMessageChunk(
            sessionUpdate="agent_message_chunk", content=TextContentBlock(type="text", text=""),
            field_meta=encode_updates(
                TranscriptSnapshotUpdate(page, read.identity),
                CoordinationChangedUpdate(comms.registry.require(session_id).incarnation, root, os.getpid(),
                                          cwd, None, None, session_id, None))))
        return LoadSessionResponse()


if __name__ == "__main__":
    DelayedLoadPeer.main()
