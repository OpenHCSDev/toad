"""Textual-facing: the conversation's submissions owner puts a locally failed prompt back in the composer,
and remote failure facts never overwrite what the user is typing."""

from unittest.mock import AsyncMock, patch

from agent_comms.acp_extension import InputFailedUpdate, QueuePromptRequest, encode_updates
from agent_comms.acp_failure import BackendDeliveryFailure

from support.agents import deliver
from toad import jsonrpc
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.conversation_submission import ImmediateInputSubmission
from toad.widgets.conversation import Conversation


class FailingAgent(Agent):
    async def send_prompt(self, prompt, **kwargs):
        raise FileNotFoundError(2, "agent socket disappeared")

    async def stop(self):
        pass


async def test_a_failure_reported_by_the_remote_side_never_overwrites_the_draft(workspace):
    async with workspace.app(size=(110, 32)) as ui:
        receiver = ui.detached_agent("fixture")
        ui.attach_agent(receiver)
        await ui.write_draft("new draft")
        for _ in range(2):
            await deliver(receiver, {
                "sessionUpdate": "session_info_update",
                "_meta": encode_updates(InputFailedUpdate("remote prompt", BackendDeliveryFailure("native preflight failed")))})
            await ui.step()
            assert ui.draft() == "new draft"
        await receiver.stop()


async def test_a_prompt_whose_request_fails_is_restored_to_the_composer(workspace):
    async with workspace.app(size=(110, 32)) as ui:
        receiver = ui.detached_agent("fixture")
        ui.attach_agent(receiver)
        for error in (jsonrpc.APIError(-32602, "Invalid params", {"reason": "owner unavailable"}),
                      jsonrpc.JSONRPCError("socket disconnected")):
            await ui.write_draft("")
            response = AsyncMock()
            response.wait.side_effect = error
            with patch("toad.acp.agent_controller.api.session_prompt", return_value=response):
                await receiver.controller.submit_blocks(
                    [{"type": "text", "text": "rpc prompt"}], QueuePromptRequest("rpc prompt"))
            await ui.until(lambda: ui.draft() == "rpc prompt", why="the failed request's text back in the draft")
        await receiver.stop()


async def test_a_prompt_the_agent_cannot_be_reached_for_is_restored_to_the_composer(workspace):
    async with workspace.app(size=(110, 32)) as ui:
        conversation = ui.conversation
        conversation.set_reactive(Conversation.agent, FailingAgent(
            workspace.project, AgentDefinition("failing", "Failing fixture", {"*": "true"}), "fixture"))
        await ui.write_draft("")
        worker = await ImmediateInputSubmission("the local failure prompt").execute(conversation.submissions)
        await worker.wait()
        await ui.until(lambda: ui.draft() == "the local failure prompt", why="the failed prompt back in the draft")
