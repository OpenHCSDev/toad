"""Textual-facing: the queue summary row and the conversation's submissions owner keep what a newer
session request produced when an older request answers late, and a failed send never rewrites the draft."""

import asyncio

import pytest
from acp.schema import NewSessionResponse
from agent_comms.acp_extension import (
    AvailableQueueProjection, QueueChangedUpdate, QueueItem, LiveQueueScope, encode_updates,
)
from agent_comms.child_process import ProcessIdentity
from agent_comms.thread_identity import ClaimedIdentity, RecordedThreadIncarnation

from support.agents import PendingAnswer, PendingConnection
from toad.widgets.prompt import QueueSummary
from acp.exceptions import RequestError


def response(session, next_owner=False):
    generation = 2 if next_owner else 1
    scope = LiveQueueScope(
        session_id=session,
        claimed_identity=ClaimedIdentity(RecordedThreadIncarnation(session, 1000.0), generation),
        owner=ProcessIdentity(1234, 1),
    )
    items = (QueueItem("a" * 32, "same text"), QueueItem("b" * 32, "same text"))
    return NewSessionResponse(
        sessionId=session, _meta=encode_updates(QueueChangedUpdate(scope, generation, AvailableQueueProjection(items))))


@pytest.mark.parametrize("successor", ["new", "stop"])
@pytest.mark.parametrize("first_kind", ["new", "load"])
async def test_late_answer_to_a_replaced_session_request_changes_neither_session_queue_nor_draft(
        workspace, first_kind, successor):
    async with workspace.app(size=(115, 38)) as ui:
        agent = ui.detached_agent("old-session" if first_kind == "load" else None)
        ui.attach_agent(agent)
        await ui.step()
        await ui.write_draft("untouched local draft")
        view = ui.conversation
        first, second = PendingAnswer(), PendingAnswer()
        agent.process.connection = PendingConnection([first, second] if first_kind == "new" else [second], first)
        pending = asyncio.create_task(agent.session.new() if first_kind == "new" else agent.session.load())
        await first.started.wait()
        if successor == "new":
            replacing = asyncio.create_task(agent.session.new())
            await second.started.wait()
            second.result.set_result(response("new-session"))
            await replacing
            await ui.until(lambda: view.submissions.queue_projection.status == "available",
                           why="the newer session's queue")
            assert agent.session_id == "new-session"
        else:
            await agent.stop()
            await ui.step()
        before = (agent.session_id, agent.queue_attachment.current, view.submissions.queue_projection)
        first.result.set_result(response("old-session"))
        # The replaced request's late answer is refused to its caller and changes nothing.
        with pytest.raises(RequestError) as refused:
            await pending
        assert "retired session" in refused.value.data["details"]
        await ui.step()
        assert (agent.session_id, agent.queue_attachment.current, view.submissions.queue_projection) == before
        assert ui.draft() == "untouched local draft"
        if successor == "new":
            app, _pilot = ui.textual
            row = view.query_one(QueueSummary)
            assert row in app.screen._compositor.visible_widgets
            assert "Queued (2)" in row.render().plain
        else:
            assert view.submissions.queue_projection.status != "available"
        await agent.stop()
