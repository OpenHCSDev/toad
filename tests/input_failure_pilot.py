from agent_comms.acp_extension import (
    InputFailedUpdate,
    QueuePromptRequest,
    encode_updates,
)
from agent_comms.acp_failure import BackendDeliveryFailure

"""Local request failures restore their text; remote failure evidence cannot inject drafts."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from runtime_fixture import ToadApp

from toad import jsonrpc
from toad.acp.agent import Agent
from toad.conversation_submission import ImmediateInputSubmission
from toad.widgets.conversation import Conversation


class FailingAgent(Agent):
    async def send_prompt(self, prompt, **kwargs):
        raise FileNotFoundError(2, "agent socket disappeared")

    async def stop(self):
        pass


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-input-failure-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            conversation = app.selected_session.conversation
            receiver = Agent(
                root, {"name": "Fixture", "run_command": {"*": "true"}}, "fixture"
            )
            receiver.attach_surface(conversation)
            conversation.set_reactive(Conversation.agent, receiver)
            conversation.prompt.text = "new draft"
            # Current public ACP metadata: a remote failure is evidence, never
            # authority to overwrite a local draft, including repeated delivery.
            for _ in range(2):
                receiver.updates.accept(
                    "fixture",
                    {
                        "sessionUpdate": "session_info_update",
                        "_meta": encode_updates(
                            InputFailedUpdate(
                                "remote prompt",
                                BackendDeliveryFailure("native preflight failed"),
                            )
                        ),
                    },
                )
                await pilot.pause()
                assert conversation.prompt.text == "new draft"

            # Exercise the real ACP request error catch, which used to consume
            # exceptions before the conversation could recover the original text.
            for error in (
                jsonrpc.APIError(
                    -32602, "Invalid params", {"reason": "owner unavailable"}
                ),
                jsonrpc.JSONRPCError("socket disconnected"),
            ):
                conversation.prompt.text = ""
                response = AsyncMock()
                response.wait.side_effect = error
                with patch("toad.acp.agent.api.session_prompt", return_value=response):
                    await receiver.controller.submit_blocks(
                        [{"type": "text", "text": "rpc prompt"}],
                        QueuePromptRequest("rpc prompt"),
                    )
                await pilot.pause()
                assert conversation.prompt.text == "rpc prompt"
            conversation.set_reactive(
                Conversation.agent,
                FailingAgent(
                    root,
                    {"name": "Failing fixture", "run_command": {"*": "true"}},
                    "fixture",
                ),
            )
            conversation.prompt.text = ""
            worker = await ImmediateInputSubmission("the local failure prompt").execute(conversation.submissions)
            await worker.wait()
            await pilot.pause()
            assert conversation.prompt.text == "the local failure prompt"
            await receiver.stop()
    print(
        "input failure: remote evidence is read-only; exact locally failed prompts are restored"
    )


if __name__ == "__main__":
    asyncio.run(main())
