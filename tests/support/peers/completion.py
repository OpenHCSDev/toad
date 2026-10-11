"""Scripted ACP agent for completion, command discovery and model selection.

- ``new_session`` waits while ``hold-acp-startup`` exists in the project, so a test controls when the agent is ready.
- Every prompt is answered with ``COMPLETION_PEER_EXECUTED <text>`` after announcing one available command,
  ``/proofcmd``, whose hint is ``ORIGINAL_ACP_HINT`` (``UPDATED_ACP_HINT`` after the prompt ``change-command``).
- The model option offers ``local/first`` and ``local/second``; a selection is recorded.

Facts are recorded in ``completion-wire.jsonl`` (read by other tests by that name) and, like every
``Peer``, in ``peer-received.jsonl``.
"""

import asyncio
import json

from acp.schema import (
    AvailableCommand, AvailableCommandsUpdate, NewSessionResponse, PromptResponse, SessionConfigOptionSelect,
    SessionConfigSelectOption, SetSessionConfigOptionResponse,
)
from base import Peer

COMPLETION_WIRE = "completion-wire.jsonl"


class CompletionPeer(Peer):
    session_id = "completion-acceptance"

    def models(self, current="local/first"):
        return [SessionConfigOptionSelect(
            id="model", name="Model", category="model", type="select", currentValue=current,
            options=[SessionConfigSelectOption(value=f"local/{name}", name=f"Local {name}")
                     for name in ("first", "second")])]

    async def new_session(self, cwd: str, **kwargs):
        await super().new_session(cwd, **kwargs)
        hold = self.project / "hold-acp-startup"
        while hold.exists():
            await asyncio.sleep(.02)
        return NewSessionResponse(sessionId=self.session_id, configOptions=self.models())

    async def prompt(self, session_id, prompt, **kwargs):
        text = prompt[0].text
        self.record(prompt=text)
        await self.connection.session_update(session_id=session_id, update=AvailableCommandsUpdate(
            sessionUpdate="available_commands_update",
            availableCommands=[AvailableCommand(
                name="proofcmd", description="Physical ACP completion command",
                input={"hint": "UPDATED_ACP_HINT" if text == "change-command" else "ORIGINAL_ACP_HINT"})]))
        await self.say(session_id, f"COMPLETION_PEER_EXECUTED {text}")
        return PromptResponse(stopReason="end_turn")

    async def set_config_option(self, config_id, session_id, value, **kwargs):
        self.record(config_id=config_id, value=value)
        return SetSessionConfigOptionResponse(configOptions=self.models(value))

    def record(self, **fact) -> None:
        super().record(**fact)
        with (self.project / COMPLETION_WIRE).open("a") as stream:
            stream.write(json.dumps(fact) + "\n")


if __name__ == "__main__":
    CompletionPeer.main()
