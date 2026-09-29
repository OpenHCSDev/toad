"""Official SDK stdio peer proves command discovery, sending and model selection."""
import asyncio
import json
from pathlib import Path

from acp import Agent, Client, run_agent
from acp.schema import (
    AgentMessageChunk, AvailableCommand, AvailableCommandsUpdate, InitializeResponse,
    NewSessionResponse, PromptResponse, SessionConfigOptionSelect,
    SessionConfigSelectOption, SetSessionConfigOptionResponse, TextContentBlock,
)


class CompletionPeer(Agent):
    def on_connect(self, conn: Client) -> None:
        self.connection = conn

    async def initialize(self, protocol_version: int, **kwargs):
        return InitializeResponse(protocolVersion=protocol_version)

    def models(self, current="local/first"):
        return [SessionConfigOptionSelect(
            id="model", name="Model", category="model", type="select", currentValue=current,
            options=[SessionConfigSelectOption(value=f"local/{name}", name=f"Local {name}")
                     for name in ("first", "second")],
        )]

    async def new_session(self, cwd: str, **kwargs):
        self.project = Path(cwd)
        return NewSessionResponse(sessionId="completion-acceptance", configOptions=self.models())

    async def prompt(self, session_id, prompt, **kwargs):
        text = prompt[0].text
        self.record({"prompt": text})
        await self.connection.session_update(session_id=session_id, update=AvailableCommandsUpdate(
            sessionUpdate="available_commands_update",
            availableCommands=[AvailableCommand(name="proofcmd", description="Physical ACP completion command")],
        ))
        await self.connection.session_update(session_id=session_id, update=AgentMessageChunk(
            sessionUpdate="agent_message_chunk",
            content=TextContentBlock(type="text", text=f"COMPLETION_PEER_EXECUTED {text}"),
        ))
        return PromptResponse(stopReason="end_turn")

    async def set_config_option(self, config_id, session_id, value, **kwargs):
        self.record({"config_id": config_id, "value": value})
        return SetSessionConfigOptionResponse(configOptions=self.models(value))

    def record(self, value):
        with (self.project / "completion-wire.jsonl").open("a") as stream:
            stream.write(json.dumps(value) + "\n")


if __name__ == "__main__":
    asyncio.run(run_agent(CompletionPeer()))
