"""Textual-facing: the conversation's submissions owner puts a locally failed prompt back in the composer,
and remote failure facts never overwrite what the user is typing."""

import asyncio
from contextlib import closing
from dataclasses import replace
import sqlite3
import sys

import pytest
from textual.worker import WorkerCancelled

from acp.exceptions import RequestError
from acp.schema import ConfigOptionUpdate, NewSessionResponse, SessionConfigOptionSelect

from agent_comms.acp_extension import (
    AvailableQueueProjection, IdentifiedInputStarted, InputFailedUpdate, LiveQueueScope,
    QueueChangedUpdate, RequestFailedUpdate, encode_updates,
)
from agent_comms.acp_failure import BackendDeliveryFailure, RequestFailure
from agent_comms.input_attempt import BoundUnknownInput, InputAttempt, NotSentInput, ReservedInput, StartedInput
from agent_comms.nominal.field_codec import AcpSessionId, InputId

from support.agents import PEERS, command, peer, script
from toad.conversation_submission import SendBlocked, SendPending
from toad.core.input_events import UserInputSubmitted
from toad.session_scope import AgentAttached


async def test_a_failure_reported_by_the_remote_side_never_overwrites_the_draft(workspace):
    async with workspace.app(size=(110, 32), binding=AgentAttached(peer("scripted"))) as ui:
        await ui.until_agent_ready()
        receiver = ui.conversation.agent_binding
        await ui.write_draft("new draft")
        remote = script({"update": {
            "sessionUpdate": "session_info_update",
            "_meta": encode_updates(InputFailedUpdate("remote prompt", BackendDeliveryFailure("native preflight failed")))}})
        for _ in range(2):
            await asyncio.wait_for(receiver.send_prompt(remote), 10)
            await ui.step()
            assert ui.draft() == "new draft"
        assert workspace.prompts_received() == [remote, remote]


@pytest.mark.parametrize(("input_state", "blocked"), (
    (None, True),
    (BoundUnknownInput, True),
    (ReservedInput, True),
    (NotSentInput, False),
    (StartedInput, False),
))
async def test_request_failure_preserves_its_reported_input_disposition(
        workspace, input_state: type[InputAttempt] | None, blocked: bool):
    async with workspace.app(size=(110, 32), binding=AgentAttached(peer("scripted"))) as ui:
        await ui.until_agent_ready()
        view = ui.conversation
        receiver = view.agent_binding
        disposition, child = receiver.session.disposition, receiver.process.process
        original = RequestFailure.from_error(RequestError.invalid_params({"reason": "owner unavailable"}))
        reported = replace(original, failure=replace(original.failure, input_state=input_state))
        error = RequestError.invalid_params(reported.error_data())
        body = script({"error": error.to_error_obj()})
        await ui.write_draft("")
        worker = await view.submissions.submit(UserInputSubmitted(body))
        (execution,) = view.submissions.active
        await asyncio.wait_for(worker.wait(), 10)
        await ui.until(lambda: ui.draft() == body, why="the failed request's original text back in the draft")
        assert receiver.session.disposition is disposition
        assert receiver.process.process is child and child.returncode is None
        if blocked:
            assert isinstance(execution.state, SendBlocked)
            assert view.submissions.retains_surface
            await view.submissions.submit(UserInputSubmitted(body))
            await ui.step()
            assert ui.draft() == body
            assert isinstance(execution.state, SendBlocked)
        else:
            assert not view.send_block_reason
            assert not view.submissions.retains_surface
        assert workspace.prompts_received() == [body], "An unconfirmed input was replayed"
        assert {"error": error.to_error_obj()} in workspace.received()


MODEL_ADVERTISEMENT = {
    "id": "model", "name": "Model", "category": "model", "type": "select",
    "currentValue": "openai-codex/gpt-5.4",
    "options": [{"value": "openai-codex/gpt-5.4", "name": "openai-codex/gpt-5.4"},
                {"value": "openai-codex/gpt-5.4-mini", "name": "openai-codex/gpt-5.4-mini"}],
}


async def test_a_provider_error_fails_its_turn_and_keeps_the_thread_and_model_selector(workspace):
    async with workspace.app(size=(110, 32), binding=AgentAttached(peer("scripted"))) as ui:
        await ui.until_agent_ready()
        view = ui.conversation
        receiver = view.agent_binding
        advertised = ConfigOptionUpdate(session_update="config_option_update", config_options=[
            SessionConfigOptionSelect.model_validate(MODEL_ADVERTISEMENT)])
        await asyncio.wait_for(receiver.send_prompt(script({
            "update": advertised.model_dump(mode="json", by_alias=True, exclude_none=True)})), 10)
        await ui.until(lambda: view.model_selection_available, why="the foreign peer's advertised model selector")
        disposition, child = receiver.session.disposition, receiver.process.process
        error = RequestError.internal_error({"details": "WebSocket error"})
        body = script({"error": error.to_error_obj()})
        await ui.write_draft("")
        worker = await view.submissions.submit(UserInputSubmitted(body))
        await asyncio.wait_for(worker.wait(), 10)
        await ui.until(lambda: ui.draft() == body, why="the failed request's original text back in the draft")
        await asyncio.wait_for(receiver.send_prompt(script({"update": {
            "sessionUpdate": "session_info_update",
            "_meta": encode_updates(RequestFailedUpdate(BackendDeliveryFailure("provider refused the model")))}})), 10)
        await ui.step()
        assert ui.draft() == body
        assert receiver.session.disposition is disposition
        assert receiver.process.process is child and child.returncode is None
        assert view.model_selection_available
        assert view.send_block_reason and view.submissions.retains_surface
        assert {"error": error.to_error_obj()} in workspace.received()


async def test_a_late_original_native_start_settles_a_failed_request_without_replaying(workspace):
    owner = workspace.thread("scope-owner", running=True)
    session = "late-ack-session"
    scope = LiveQueueScope(
        session_id=AcpSessionId(session),
        claimed_identity=workspace.comms.registry.snapshot().claimed_identity(owner.name),
        owner=owner.require_process(),
    )
    response = NewSessionResponse(sessionId=session, _meta=encode_updates(
        QueueChangedUpdate(scope, 1, AvailableQueueProjection())))
    response_path = workspace.project / "late-session.json"
    response_path.write_text(response.model_dump_json(by_alias=True))
    definition = command(sys.executable, str(PEERS / "session_response.py"), str(response_path))
    async with workspace.app(size=(110, 32), binding=AgentAttached(definition)) as ui:
        await ui.until_agent_ready()
        view = ui.conversation
        receiver = view.agent_binding
        assert receiver.queue_attachment.accepts_request(scope), "The SDK session response did not bind its scope"
        assert not receiver.presentation.queue_supported, "A queue observation must not invent coordination"
        original = RequestFailure.from_error(RequestError.internal_error({"details": "lost input disposition"}))
        failure = replace(original, failure=replace(original.failure, input_state=BoundUnknownInput))
        body = script({"error": RequestError.internal_error(failure.error_data()).to_error_obj()})
        await ui.write_draft("")
        worker = await view.submissions.submit(UserInputSubmitted(body))
        (execution,) = view.submissions.active
        await asyncio.wait_for(worker.wait(), 10)
        await ui.until(lambda: ui.draft() == body, why="the uncertain input's retained draft")
        assert isinstance(execution.state, SendBlocked)
        await view.submissions.submit(UserInputSubmitted(body))
        assert workspace.prompts_received().count(body) == 1
        started = IdentifiedInputStarted(body, scope, 2, InputId.mint(), execution.request.input_id)
        await asyncio.wait_for(receiver.send_prompt(script({"update": {
            "sessionUpdate": "session_info_update", "_meta": encode_updates(started)}})), 10)
        await ui.until(lambda: not view.submissions.retains_surface,
                       why="the late original native acknowledgement to retire its completed request")
        assert not view.send_block_reason
        assert ui.draft() == body  # A later observation cannot delete the user's inspection draft.
        assert workspace.prompts_received().count(body) == 1
        assert receiver.session.connected


async def test_a_lost_held_peer_retains_unknown_and_refuses_retry(workspace):
    async with workspace.app(size=(110, 32), binding=AgentAttached(peer("scripted"))) as ui:
        await ui.until_agent_ready()
        view = ui.conversation
        receiver = view.agent_binding
        body = script({"wait": "lost-transport"})
        await ui.write_draft("")
        worker = await view.submissions.submit(UserInputSubmitted(body))
        await ui.until(lambda: workspace.prompts_received() == [body], why="the original request at the actual held peer")
        (execution,) = view.submissions.active
        child = receiver.process.process
        await asyncio.wait_for(child.stop(), 10)
        try:
            await asyncio.wait_for(worker.wait(), 10)
        except WorkerCancelled:
            pass  # Session retirement may cancel its caller; its shared completion still settles.
        await ui.until(lambda: ui.draft() == body, why="the lost request's body retained for inspection")
        assert isinstance(execution.state, SendBlocked)
        assert view.submissions.retains_surface
        assert receiver.session.disposition.failure is not None
        assert not receiver.session.connected
        await view.submissions.submit(UserInputSubmitted(body))
        await ui.step()
        assert workspace.prompts_received() == [body], "The uncertain request was replayed"
        assert ui.draft() == body
        assert isinstance(execution.state, SendBlocked)


async def test_a_prompt_the_agent_cannot_be_reached_for_is_restored_to_the_composer(workspace):
    missing = workspace.project / "missing-acp-command"
    assert not missing.exists()
    async with workspace.app(size=(110, 32), binding=AgentAttached(command(str(missing)))) as ui:
        view = ui.conversation
        receiver = view.agent_binding
        await ui.until(receiver.session.settled.is_set, seconds=20, why="the actual failed command launch")
        assert not receiver.ready
        assert receiver.session.disposition.failure is not None
        await ui.write_draft("")
        body = "the local failure prompt"
        await view.submissions.submit(UserInputSubmitted(body))
        await ui.until(lambda: ui.draft() == body, why="the refused local input back in the draft")
        assert not view.send_block_reason
        assert not view.submissions.retains_surface
        assert not workspace.prompts_received()


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
    comms.messaging.send("peer", workspace.viewer, "READY_BUS_WRITE_SOURCE")
    async with workspace.app(size=(110, 32)) as ui:
        await ui.open_direct("peer", actor=workspace.viewer)
        await ui.until_shows("READY_BUS_WRITE_SOURCE")
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
