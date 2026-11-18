"""`ui.input.delivery_preview`: the queue rows above the prompt, or only the info bar's held count."""

import asyncio

from support.agents import PendingAnswer, PendingConnection, queued_session_response
from toad.preferences import SETTINGS
from toad.widgets.prompt import DeliveryControls, QueueHint, QueueSummary


async def test_turning_the_delivery_preview_off_drops_the_queue_rows_for_the_held_count_live(workspace):
    async with workspace.app(size=(115, 38)) as ui:
        agent = ui.detached_agent(None)
        ui.attach_agent(agent)
        await ui.step()
        view = ui.conversation
        answer = PendingAnswer()
        agent.process.connection = PendingConnection([answer], answer)
        starting = asyncio.create_task(agent.session.new())
        await answer.started.wait()
        answer.result.set_result(queued_session_response("new-session"))
        await starting
        await ui.until(lambda: view.submissions.queue_projection.status == "available", why="the queue")
        app, _pilot = ui.textual
        summary, held = view.query_one(QueueSummary), view.query_one(QueueHint)
        assert "Queued (2)" in summary.render().plain and summary.display
        assert not held.display

        app.saved_settings.set(SETTINGS.ui.input.delivery_preview, False)
        await ui.step()
        assert not summary.display
        assert not view.query_one(DeliveryControls).display
        assert held.display and held.render().plain == "⧗ 2 held"

        app.saved_settings.set(SETTINGS.ui.input.delivery_preview, True)
        await ui.step()
        assert summary.display and "Queued (2)" in summary.render().plain
        assert not held.display
        await agent.stop()
