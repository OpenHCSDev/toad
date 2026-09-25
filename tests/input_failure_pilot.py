"""A preflight rejection restores the exact prompt in the composer."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent_comms.acp import CommsAgent
from agent_comms.operations import wire
from runtime_fixture import ToadApp
from toad import jsonrpc
from toad.acp.agent import Agent
from toad.widgets.conversation import Conversation


class FailingAgent:
    uses_turn_events = False

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
            conversation = app.screen.conversation
            receiver = Agent(root, {"name": "Fixture", "run_command": {"*": "true"}}, "fixture")
            receiver._message_target = conversation
            conversation.set_reactive(Conversation.agent, receiver)
            received = []

            class SerializedClient:
                async def session_update(self, *, session_id, update):
                    payload = json.loads(update.model_dump_json(by_alias=True, exclude_none=True))
                    received.append(payload)
                    receiver.rpc_session_update(session_id, payload)

            # A real child accepts get_state then exits without attestation.
            # No synthesized backend error event: this exercises its terminal done path.
            child = root / "pi-preflight-exit"
            child.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.readline()\n")
            child.chmod(0o700)
            server = CommsAgent(wire(root / "wire"), agent_bin=str(child), agent_args=[])
            server._client = SerializedClient()
            with patch.dict(os.environ, {"AGENT_COMMS_AGENT_MODELS": "test/model"}):
                await server.new_session(cwd=str(root / "fixture"), mcp_servers=[])
            prompt = "the exact prompt\n\nwith another paragraph"
            conversation.prompt.text = "new draft"
            try:
                await server._run_owned_input("fixture", "fixture", prompt)
                await pilot.pause()
                failures = [p for p in received if p.get("_meta", {}).get("agentComms", {}).get("inputFailed")]
                assert len(failures) == 1, received
                failure = failures[0]["_meta"]["agentComms"]["inputFailed"]
                assert "preflight ended before attestation" in failure["reason"]
                assert conversation.prompt.text == "new draft\n\n" + prompt
                receiver.rpc_session_update("fixture", failures[0])
                await pilot.pause()
                assert conversation.prompt.text == "new draft\n\n" + prompt
                assert not server._turn_input_text
                assert not server._turn_original_input_keys
            finally:
                await server.shutdown()

            # Exercise the real ACP request error catch, which used to consume
            # exceptions before the conversation could recover the original text.
            for error in (
                jsonrpc.APIError(-32602, "Invalid params", {"reason": "owner unavailable"}),
                jsonrpc.JSONRPCError("socket disconnected"),
            ):
                conversation.prompt.text = ""
                response = AsyncMock()
                response.wait.side_effect = error
                with patch("toad.acp.agent.api.session_prompt", return_value=response):
                    await receiver.acp_session_prompt(
                        [{"type": "text", "text": "rpc prompt"}],
                        {"agentComms": {"userText": "rpc prompt"}},
                    )
                await pilot.pause()
                assert conversation.prompt.text == "rpc prompt"
            conversation.set_reactive(Conversation.agent, FailingAgent())
            conversation.prompt.text = ""
            await conversation.send_prompt_to_agent(
                "the local failure prompt", immediate=True
            ).wait()
            await pilot.pause()
            assert conversation.prompt.text == "the local failure prompt"
            await receiver.stop()
    print("input failure: exact prompt restored after preflight rejection")


if __name__ == "__main__":
    asyncio.run(main())
