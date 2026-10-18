"""Textual-facing: the native history row and the conversation's history status keep what a newer session
request proved when an older request answers late."""

import asyncio
from unittest.mock import patch

import pytest
from acp.schema import NewSessionResponse
from agent_comms.acp_extension import (
    CursorAdvancedUpdate, CursorEnvelope, LiveCursorScope, VerifiedCursorObservation, encode_updates,
)
from agent_comms.native_input_record import FullNativeExecution
from agent_comms.native_runtime_input import CurrentNativeCursor
from agent_comms.thread_identity import AdmissionIdentity, RecordedThreadIncarnation

from support.agents import detached
from support.textual_steps import reveal_session_details
from toad.widgets.native_history import NativeHistory
from toad.private_native_cursor import CursorStatus, ProvenCursorStatus
from toad.jsonrpc import InvalidParams


def response(session):
    owner = AdmissionIdentity(RecordedThreadIncarnation("owner", 1000.0), 1)
    cursor = CurrentNativeCursor(
        wire_root_id="a" * 32, recipient_lookup="recipient", owner_thread="owner", owner_generation=1,
        owner_admission_generation=1, covered_seq=2, injected_seq=2, input_id="b" * 32,
        stage=FullNativeExecution, session_id="native-session", request_generation=1)
    fact = CursorAdvancedUpdate(CursorEnvelope(
        LiveCursorScope(session, "a" * 32, owner, 1234), 1, VerifiedCursorObservation(cursor)))
    return NewSessionResponse(sessionId=session, _meta=encode_updates(fact))


def test_unknown_cursor_status_is_rejected():
    with pytest.raises(ValueError, match="Unknown CursorStatus name"):
        CursorStatus.external("future-status")


class Response:
    def __init__(self):
        self.started = asyncio.Event()
        self.result = asyncio.get_running_loop().create_future()

    async def wait(self):
        self.started.set()
        return await self.result


@pytest.mark.parametrize("successor", ["new", "stop"])
@pytest.mark.parametrize("first_kind", ["new", "load"])
async def test_late_answer_to_a_replaced_session_request_cannot_change_session_or_history_proof(
        workspace, first_kind, successor):
    async with workspace.app(size=(115, 38)) as ui:
        agent = detached(workspace.project, "old-session" if first_kind == "load" else None)
        ui.attach_agent(agent)
        await ui.step()
        view = ui.conversation
        first, second = Response(), Response()
        new_responses = [first, second] if first_kind == "new" else [second]
        with (patch("toad.acp.agent_session.api.session_new", side_effect=new_responses),
              patch("toad.acp.agent_session.api.session_load", return_value=first) as load):
            call = agent.session.new if first_kind == "new" else agent.session.load
            pending = asyncio.create_task(call())
            await first.started.wait()
            if first_kind == "load":
                assert load.call_args.args[2] == "old-session"
            if successor == "new":
                replacement = asyncio.create_task(agent.session.new())
                await second.started.wait()
                second.result.set_result(response("new-session"))
                await replacement
                await ui.until(lambda: view.native_history_status is ProvenCursorStatus, why="the newer session's proof")
                assert agent.session_id == "new-session"
            else:
                await agent.stop()
                await ui.step()
            sequence = agent._private_cursor_sequence
            current_session = agent.session_id
            status = view.native_history_status
            first.result.set_result(response("old-session"))
            # The replaced request's late answer is refused to its caller and changes nothing.
            with pytest.raises(InvalidParams, match="retired session"):
                await pending
            await ui.step()
        assert agent.session_id == current_session
        assert agent._private_cursor_sequence == sequence
        assert view.native_history_status == status
        if successor == "new":
            assert agent._private_cursor.current.scope.session_id == "new-session"
            row = view.query_one(NativeHistory)
            await reveal_session_details(ui, row)
            app, _pilot = ui.textual
            assert row.display and row in app.screen._compositor.visible_widgets
        else:
            assert agent._private_cursor.current is None
            assert status is not ProvenCursorStatus
        await agent.stop()
