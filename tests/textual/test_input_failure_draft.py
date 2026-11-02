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
    QueueChangedUpdate, RequestFailedUpdate, decode_request, encode_updates,
)
from agent_comms.acp_failure import BackendDeliveryFailure, RequestFailure
from agent_comms.channel_targets import ThreadTarget
from agent_comms.repo import Checkout
from agent_comms.input_attempt import BoundUnknownInput, InputAttempt, NotSentInput, ReservedInput, StartedInput
from agent_comms.nominal.field_codec import AcpSessionId, InputId

from support.agents import PEERS, command, peer, script
from toad.acp.agent import NativeInputPresented
from toad.conversation_submission import SendBlocked, SendPending, SentAwaitingSource
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
        worker = await view.submit(UserInputSubmitted(body))
        (execution,) = view.pending_submissions
        await asyncio.wait_for(worker.wait(), 10)
        await ui.until(lambda: ui.draft() == body, why="the failed request's original text back in the draft")
        assert receiver.session.disposition is disposition
        assert receiver.process.process is child and child.returncode is None
        if blocked:
            assert isinstance(execution.state, SendBlocked)
            assert view.retains_surface
            await view.submit(UserInputSubmitted(body))
            await ui.step()
            assert ui.draft() == body
            assert isinstance(execution.state, SendBlocked)
        else:
            assert not view.send_block_reason
            assert not view.retains_surface
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
        worker = await view.submit(UserInputSubmitted(body))
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
        assert view.send_block_reason and view.retains_surface
        assert {"error": error.to_error_obj()} in workspace.received()


@pytest.mark.parametrize("acknowledge_before_reply", (False, True))
async def test_original_native_start_settles_a_failed_request_without_replaying(
        workspace, acknowledge_before_reply: bool):
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
        body = script({"wait": "request-error-ready"},
                      {"error": RequestError.internal_error(failure.error_data()).to_error_obj()})
        await ui.write_draft("")
        worker = await view.submit(UserInputSubmitted(body))
        (execution,) = view.pending_submissions
        await ui.until(lambda: workspace.prompts_received() == [body], why="the captured input at the held SDK peer")
        metadata = next(fact["metadata"] for fact in workspace.received() if fact.get("prompt") == body)
        assert decode_request(**metadata) == execution.request, "The peer received a second request identity"
        started = IdentifiedInputStarted(body, scope, 2, InputId.mint(), execution.request.input_id)
        acknowledgement = script({"update": {
            "sessionUpdate": "session_info_update", "_meta": encode_updates(started)}})
        if acknowledge_before_reply:
            await asyncio.wait_for(receiver.send_prompt(acknowledgement), 10)
            await ui.until(lambda: isinstance(execution.state, NativeInputPresented), why="input acknowledged before its error reply")
            assert not worker.is_finished and execution in view.pending_submissions
        workspace.release("request-error-ready")
        await asyncio.wait_for(worker.wait(), 10)
        if acknowledge_before_reply:
            await ui.step()
            assert ui.draft() == "", "A negative reply resurrected input already acknowledged"
        else:
            await ui.until(lambda: ui.draft() == body, why="the uncertain input's retained draft")
            assert isinstance(execution.state, SendBlocked)
            await view.submit(UserInputSubmitted(body))
            assert workspace.prompts_received().count(body) == 1
            await asyncio.wait_for(receiver.send_prompt(acknowledgement), 10)
            assert ui.draft() == body  # A later observation cannot delete the user's inspection draft.
        await ui.until(lambda: not view.retains_surface,
                       why="the original acknowledgement and completed response to retire their request")
        assert not view.send_block_reason
        assert workspace.prompts_received().count(body) == 1
        assert receiver.session.connected


async def test_a_lost_held_peer_retains_unknown_and_refuses_retry(workspace):
    async with workspace.app(size=(110, 32), binding=AgentAttached(peer("scripted"))) as ui:
        await ui.until_agent_ready()
        view = ui.conversation
        receiver = view.agent_binding
        body = script({"wait": "lost-transport"})
        await ui.write_draft("")
        worker = await view.submit(UserInputSubmitted(body))
        await ui.until(lambda: workspace.prompts_received() == [body], why="the original request at the actual held peer")
        (execution,) = view.pending_submissions
        child = receiver.process.process
        await asyncio.wait_for(child.stop(), 10)
        try:
            await asyncio.wait_for(worker.wait(), 10)
        except WorkerCancelled:
            pass  # Session retirement may cancel its caller; its shared completion still settles.
        await ui.until(lambda: ui.draft() == body, why="the lost request's body retained for inspection")
        assert isinstance(execution.state, SendBlocked)
        assert view.retains_surface
        assert receiver.session.disposition.failure is not None
        assert not receiver.session.connected
        await view.submit(UserInputSubmitted(body))
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
        await view.submit(UserInputSubmitted(body))
        await ui.until(lambda: ui.draft() == body, why="the refused local input back in the draft")
        assert not view.send_block_reason
        assert not view.retains_surface
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
        worker = await chat.submit(UserInputSubmitted("CANCELLED_BEFORE_START"))
        worker.cancel()  # No yield between admission and cancellation: the callable never ran.
        with pytest.raises(WorkerCancelled):
            await asyncio.wait_for(worker.wait(), 10)
        await chat.close_submissions()
        assert chat.prompt.text == "Different draft\n\nCANCELLED_BEFORE_START"
        assert editor.document is document and editor.history is history
        assert not chat.retains_surface
        assert not chat.send_block_reason
        assert bus.revision() == before


@pytest.mark.parametrize("close_app", (False, True))
async def test_cancelled_bus_write_keeps_unknown_and_never_retries_the_publication(
    workspace, close_app,
):
    workspace.thread("peer")
    comms = workspace.comms
    body = "CANCELLED_DURING_REAL_BUS_WRITE"
    # Equal text from an older message is not acknowledgement of this write.
    previous = comms.messaging.send_user_message(
        ThreadTarget("peer"), body, worktree=Checkout(workspace.project),
    )
    async with workspace.app(size=(110, 32)) as ui:
        await ui.open_direct("peer", actor=workspace.viewer)
        await ui.until_shows(body)
        chat = ui.conversation
        assert chat.contains_user_message(previous)
        await ui.write_draft("An unrelated unsent draft")
        editor = chat.prompt.prompt_text_area
        document, history = editor.document, editor.history
        bus = comms.bus.bus
        before = bus.revision()
        close_task = None
        # Hold SQLite's actual writer; readers and the original UI stay live.
        with closing(sqlite3.connect(bus.path)) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            try:
                worker = await chat.submit(UserInputSubmitted(body))
                (execution,) = chat.pending_submissions
                await ui.until(lambda: isinstance(execution.state, SendPending),
                               why="the original write admitted by preparation")
                publication = execution.publication
                assert publication is not None
                assert publication in ui.app.preparation._thread_tasks
                worker.cancel()
                await asyncio.wait_for(worker.wait(), 10)
                assert isinstance(execution.state, SendBlocked)
                assert not publication.done()
                assert chat.retains_surface
                assert chat.prompt.text == "An unrelated unsent draft\n\n" + body
                restored = editor.text
                await chat.submit(UserInputSubmitted(body))
                assert bus.revision() == before
                if close_app:
                    # Run the application's real close owner, including view
                    # release and the preparation lifetime, while SQLite is held.
                    close_task = asyncio.create_task(ui.app._close_all())
                    async with asyncio.timeout(10):
                        while not ui.app.preparation._closed and not close_task.done():
                            await asyncio.sleep(.01)
                    assert ui.app.preparation._closed
                    assert not close_task.done(), "app close passed the admitted physical writer"
                    assert not publication.done()
            finally:
                blocker.rollback()
        sent = await asyncio.wait_for(asyncio.shield(publication), 10)
        assert sent.body == body and sent.message_id != previous.message_id
        assert execution.root == comms.root
        if close_app:
            await asyncio.wait_for(close_task, 15)
            assert isinstance(execution.state, SentAwaitingSource)
            assert execution.state.sent is sent
            assert chat.retains_surface, "a closed view has supplied no source ACK"
        else:
            await ui.until(lambda: not chat.send_block_reason,
                           why="the exact original publication acknowledged by its source")
            assert chat.contains_user_message(sent)
            assert not chat.retains_surface
        assert bus.revision() == before + 1
        assert editor.text == restored
        assert editor.document is document and editor.history is history
        assert publication.done()
        if close_app:
            assert not ui.app.preparation._thread_tasks
