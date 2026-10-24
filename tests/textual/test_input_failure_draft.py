"""Textual-facing: the conversation's submissions owner puts a locally failed prompt back in the composer,
and remote failure facts never overwrite what the user is typing."""

from unittest.mock import patch

from acp.exceptions import RequestError

from agent_comms.acp_extension import InputFailedUpdate, QueuePromptRequest, RequestFailedUpdate, encode_updates
from agent_comms.acp_failure import BackendDeliveryFailure

from support.agents import deliver
from toad.conversation_submission import ImmediateInputSubmission
from toad.core.input_events import UserInputSubmitted


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
        for error in (RequestError.invalid_params({"reason": "owner unavailable"}),
                      ConnectionError("socket disconnected")):
            # A lost transport closes its session, so each failure gets its own agent.
            receiver = ui.detached_agent("fixture")
            ui.attach_agent(receiver)
            await ui.write_draft("")
            with patch.object(receiver.process, "prompt", side_effect=error):
                await receiver.controller.submit_blocks(
                    [{"type": "text", "text": "rpc prompt"}], QueuePromptRequest("rpc prompt"))
            await ui.until(lambda: ui.draft() == "rpc prompt", why="the failed request's text back in the draft")
            if isinstance(error, ConnectionError):
                failure = receiver.session.disposition.failure
                assert "Unconfirmed" in failure.details
                assert "before deciding whether to send again" in failure.details
            await receiver.stop()


MODEL_ADVERTISEMENT = {
    "id": "model", "name": "Model", "category": "model", "type": "select",
    "currentValue": "openai-codex/gpt-5.4",
    "options": [{"value": "openai-codex/gpt-5.4", "name": "openai-codex/gpt-5.4"},
                {"value": "openai-codex/gpt-5.4-mini", "name": "openai-codex/gpt-5.4-mini"}],
}


async def test_a_provider_error_fails_its_turn_and_keeps_the_thread_and_model_selector(workspace):
    from acp import schema

    async with workspace.app(size=(110, 32)) as ui:
        receiver = ui.detached_agent("fixture")
        ui.attach_agent(receiver)
        receiver.configuration.receive([schema.SessionConfigOptionSelect.model_validate(MODEL_ADVERTISEMENT)])
        disposition = receiver.session.disposition
        assert ui.conversation.model_selection_available
        await ui.write_draft("")
        with patch.object(receiver.process, "prompt",
                          side_effect=RequestError.internal_error({"details": "WebSocket error"})):
            await receiver.controller.submit_blocks(
                [{"type": "text", "text": "rpc prompt"}], QueuePromptRequest("rpc prompt"))
        await ui.until(lambda: ui.draft() == "rpc prompt", why="the failed request's text back in the draft")
        await deliver(receiver, {
            "sessionUpdate": "session_info_update",
            "_meta": encode_updates(RequestFailedUpdate(BackendDeliveryFailure("provider refused the model")))})
        await ui.step()
        assert receiver.session.disposition is disposition
        assert ui.conversation.model_selection_available
        await receiver.stop()


async def test_a_prompt_the_agent_cannot_be_reached_for_is_restored_to_the_composer(workspace):
    async with workspace.app(size=(110, 32)) as ui:
        conversation = ui.conversation
        receiver = ui.detached_agent("fixture")
        ui.attach_agent(receiver)
        await ui.write_draft("")
        with patch.object(receiver.process, "prompt", side_effect=FileNotFoundError(2, "agent socket disappeared")):
            worker = await ImmediateInputSubmission("the local failure prompt").execute(conversation.submissions)
            await worker.wait()
        await ui.until(lambda: ui.draft() == "the local failure prompt", why="the failed prompt back in the draft")
        await receiver.stop()


async def test_a_successful_wire_send_keeps_a_different_unsent_draft(workspace):
    from toad.widgets.comms_chat import CommsChatView

    comms = workspace.comms
    workspace.thread("peer")
    async with workspace.app(size=(110, 32)) as ui:
        await ui.open_direct("peer", actor=workspace.viewer)
        chat = ui.app.selected_session.query_one(CommsChatView)
        await ui.write_draft("A different unsent draft")
        editor = chat.prompt.prompt_text_area
        document, history = editor.document, editor.history
        await chat.submit_input(UserInputSubmitted("The submitted message"))
        await ui.until(lambda: ui.shows("The submitted message") and not chat.send_block_reason,
                       why="the committed message drawn and composing released")
        assert chat.prompt.text == "A different unsent draft"
        assert editor.document is document and editor.history is history


async def test_a_sent_message_scrolled_past_by_a_long_reply_still_releases_composing(workspace):
    """Drawn means in the history's drawn rows, not inside the viewport: a long reply
    landing in the same read pushes the sent message off screen, and composing must open."""
    from toad.delivery_failure_view import DeliveryFailureView
    from toad.widgets.comms_chat import CommsChatView

    comms = workspace.comms
    workspace.thread("peer")
    commit = DeliveryFailureView.commit_user_message

    async def commit_then_reply(view, *args, **kwargs):
        sent = await commit(view, *args, **kwargs)
        comms.messaging.send("peer", workspace.viewer, "\n\n".join(f"reply line {n}" for n in range(80)))
        return sent

    async with workspace.app(size=(110, 24)) as ui:
        await ui.open_direct("peer", actor=workspace.viewer)
        chat = ui.app.selected_session.query_one(CommsChatView)
        with patch.object(DeliveryFailureView, "commit_user_message", commit_then_reply):
            await chat.submit_input(UserInputSubmitted("SCROLLED_PAST_SEND"))
            await ui.until(lambda: ui.shows("reply line 79") and not chat.send_block_reason,
                           why="the long reply drawn and composing released")
        assert not ui.shows("SCROLLED_PAST_SEND")
