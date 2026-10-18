"""Textual-facing: the queue summary row and the conversation's submissions owner keep what a newer
session request produced when an older request answers late, and a failed send never rewrites the draft."""

import asyncio
from unittest.mock import patch

import pytest
from acp.schema import NewSessionResponse
from agent_comms.acp_extension import (
    AvailableQueueProjection, QueueChangedUpdate, QueueItem, LiveQueueScope, NoQueueScope, UnavailableQueueProjection,
    encode_updates,
)
from agent_comms.thread_identity import AdmissionIdentity, RecordedThreadIncarnation

from support.agents import deliver, detached
from toad.conversation_submission import DeferredInputSubmission
from toad.widgets.prompt import QueueSummary
from toad.jsonrpc import InvalidParams


def response(session, next_owner=False):
    generation = 2 if next_owner else 1
    scope = LiveQueueScope(session, AdmissionIdentity(RecordedThreadIncarnation(session, 1000.0), generation), 1234)
    items = (QueueItem("a" * 32, "same text"), QueueItem("b" * 32, "same text"))
    return NewSessionResponse(
        sessionId=session, _meta=encode_updates(QueueChangedUpdate(scope, generation, AvailableQueueProjection(items))))


class Response:
    def __init__(self):
        self.started = asyncio.Event()
        self.result = asyncio.get_running_loop().create_future()

    async def wait(self):
        self.started.set()
        return await self.result


@pytest.mark.parametrize("successor", ["new", "stop"])
@pytest.mark.parametrize("first_kind", ["new", "load"])
async def test_late_answer_to_a_replaced_session_request_changes_neither_session_queue_nor_draft(
        workspace, first_kind, successor):
    async with workspace.app(size=(115, 38)) as ui:
        agent = detached(workspace.project, "old-session" if first_kind == "load" else None)
        ui.attach_agent(agent)
        await ui.step()
        await ui.write_draft("untouched local draft")
        view = ui.conversation
        first, second = Response(), Response()
        with (patch("toad.acp.agent_session.api.session_new",
                    side_effect=[first, second] if first_kind == "new" else [second]),
              patch("toad.acp.agent_session.api.session_load", return_value=first)):
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
            with pytest.raises(InvalidParams, match="retired session"):
                await pending
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


@pytest.mark.parametrize("successor", ["agent", "owner", "unavailable"])
async def test_a_failed_retired_send_does_not_roll_back_the_successors_draft_or_queue(workspace, successor):
    async with workspace.app(size=(115, 38)) as ui:
        agent = detached(workspace.project, "beta")
        ui.attach_agent(agent)
        view = ui.conversation
        loaded = Response()
        loaded.result.set_result(response("beta"))
        with patch("toad.acp.agent_session.api.session_load", return_value=loaded):
            await agent.session.load()
        await ui.step()
        entered, release = asyncio.Event(), asyncio.Event()

        async def failed_send(*args, **kwargs):
            entered.set()
            await release.wait()
            raise ValueError("delayed old request failure")

        with patch.object(agent, "send_prompt", side_effect=failed_send):
            worker = await DeferredInputSubmission("old request").execute(view.submissions)
            await entered.wait()
            if successor == "agent":
                ui.attach_agent(detached(workspace.project, "beta"))
            elif successor == "owner":
                loaded = Response()
                loaded.result.set_result(response("beta", next_owner=True))
                with patch("toad.acp.agent_session.api.session_load", return_value=loaded):
                    await agent.session.load()
            else:
                await deliver(agent, {
                    "sessionUpdate": "session_info_update",
                    "_meta": encode_updates(QueueChangedUpdate(NoQueueScope(), 10, UnavailableQueueProjection()))},
                    session_id="beta")
            await ui.step()
            await ui.write_draft("successor draft")
            projection = view.submissions.queue_projection
            release.set()
            await worker.wait()
            await ui.step()
            assert ui.draft() == "successor draft"
            assert view.submissions.queue_projection == projection
