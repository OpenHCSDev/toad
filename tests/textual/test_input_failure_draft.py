"""Textual-facing: the conversation's submissions owner puts a locally failed prompt back in the composer,
and remote failure facts never overwrite what the user is typing."""

import asyncio
from contextlib import closing
import sqlite3
from unittest.mock import patch

import pytest
from textual.worker import WorkerCancelled

from acp.exceptions import RequestError

from agent_comms.acp_extension import InputFailedUpdate, QueuePromptRequest, RequestFailedUpdate, encode_updates
from agent_comms.acp_failure import BackendDeliveryFailure

from support.agents import deliver
from toad.conversation_submission import ImmediateInputSubmission, SendBlocked, SendPending
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
        (sent,) = comms.bus.bus.latest_addressed(
            frozenset((workspace.viewer,)), frozenset(("peer",)))
        assert sent.body == "The submitted message"
        reply = "\n\n".join(f"LONG_REPLY_{line}" for line in range(200))
        comms.messaging.send("peer", workspace.viewer, reply)
        chat.window.jump_to_latest()
        await ui.until(lambda: "LONG_REPLY_199" in ui.painted(chat.window),
                       why="the real long reply at the latest viewport")
        assert "The submitted message" not in ui.painted(chat.window)
        assert chat.contains_user_message(sent), "the loaded source still contains the original commit"
        assert not chat.send_block_reason
        assert chat.prompt.text == "A different unsent draft"
        assert editor.document is document and editor.history is history


async def test_cancelling_before_worker_start_restores_the_same_editor_without_sending(workspace):
    workspace.thread("peer")
    async with workspace.app(size=(110, 32)) as ui:
        await ui.open_direct("peer", actor=workspace.viewer)
        chat = ui.conversation
        await ui.write_draft("Different draft")
        editor = chat.prompt.prompt_text_area
        document, history = editor.document, editor.history
        bus = workspace.comms.bus.bus
        before = bus.revision()
        worker = await chat.submissions.submit(UserInputSubmitted("CANCELLED_BEFORE_START"))
        worker.cancel()  # No yield between admission and cancellation: the callable never ran.
        with pytest.raises(WorkerCancelled):
            await asyncio.wait_for(worker.wait(), 10)
        await chat.submissions.close()
        assert chat.prompt.text == "Different draft\n\nCANCELLED_BEFORE_START"
        assert editor.document is document and editor.history is history
        assert not chat.submissions.retains_surface
        assert not chat.send_block_reason
        assert bus.revision() == before


async def test_cancelled_bus_write_keeps_unknown_and_never_retries_the_publication(workspace):
    workspace.thread("peer")
    comms = workspace.comms
    async with workspace.app(size=(110, 32)) as ui:
        await ui.open_direct("peer", actor=workspace.viewer)
        chat = ui.conversation
        body = "CANCELLED_DURING_REAL_BUS_WRITE"
        await ui.write_draft("")
        bus = comms.bus.bus
        before = bus.revision()
        # Hold SQLite's real writer, not a patched messaging method. Readers still run.
        with closing(sqlite3.connect(bus.path)) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            try:
                worker = await chat.submissions.submit(UserInputSubmitted(body))
                (execution,) = chat.submissions.active
                await ui.until(lambda: isinstance(execution.state, SendPending),
                               why="the original write handed to its worker")
                worker.cancel()
                await asyncio.wait_for(worker.wait(), 10)
                assert isinstance(execution.state, SendBlocked)
                assert chat.submissions.retains_surface
                assert chat.prompt.text == body
            finally:
                blocker.rollback()
        # The shielded original may finish; observing it is not permission to replay.
        await ui.until(lambda: bus.revision() > before, why="the original publication after writer relief")
        (sent,) = bus.latest_addressed(frozenset((workspace.viewer,)), frozenset(("peer",)))
        assert sent.body == body
        assert execution.root == comms.root
        assert isinstance(execution.state, SendBlocked)
        await chat.submissions.submit(UserInputSubmitted(body))
        await chat.submissions.close()
        assert bus.revision() == before + 1
        assert chat.prompt.text == body
        assert chat.submissions.retains_surface
