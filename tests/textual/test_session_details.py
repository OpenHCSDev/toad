"""Textual-facing: the session details disclosure (a Textual Collapsible) takes one row when closed, a bounded height when open, and sits above the composer without moving live activity or the draft."""

import pytest
from textual.screen import Screen
from textual.widgets import Input

from agent_comms.messages import Message, MessageType
from agent_comms.presentation import MessageNotification
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.ui_model.delivery import InputDelivery
from agent_comms.ui_model.status import ThreadStatusModel
from toad.widgets.conversation import TurnActivity
from toad.widgets.input_delivery import InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.session_details import SessionDetails


@pytest.mark.parametrize("ansi", [False, True], ids=["rgb", "ansi"])
async def test_details_are_one_row_until_opened_and_then_bounded(workspace, ansi):
    notifications = tuple(MessageNotification(
        "owner", "Responded", "", message=Message("peer", "#comms", f"Notice {index}: " + "body " * 30,
                                                 MessageType.INFO, seq=index + 1),
    ) for index in range(30))
    state = ThreadPresentation("owner", "●", "Ready", notifications=notifications)
    history = NativeHistory()
    history.status = "none"
    delivery = InputDeliveryBar()
    delivery.delivery = InputDelivery(dismissed_historical_count=5)
    details = SessionDetails(history=history, delivery=delivery)

    class Example(Screen):
        def compose(self):
            yield details
            yield Input("Untouched draft", id="composer")

    async with workspace.app(size=(90, 30)) as ui:
        app, pilot = ui.textual
        app.ansi_color = ansi
        await app.push_screen(Example())
        details.activity.show(ThreadStatusModel.known("owner", state))
        await ui.until(lambda: details.activity.row is not None and details.size.height, why="the details row")
        composer = app.screen.query_one(Input)
        assert details.collapsed and details.size.height == 1
        frame = ui.visible_text()
        assert "Session details" in frame and "30 recent" in frame and "5 notices" in frame
        assert "Notice 0" not in frame and "Bus history:" not in frame
        assert composer.region.y == details.region.bottom

        assert await pilot.click(details.query_one("CollapsibleTitle"))
        await ui.step()
        assert not details.collapsed and details.size.height <= details.DETAIL_ROWS + 1
        assert "Recent incoming messages" in str(details.activity.render())
        history.scroll_visible(animate=False, immediate=True)
        await ui.step()
        assert history in app.screen._compositor.visible_widgets
        assert "no verified input" in str(history.render())
        details.collapsed = True
        delivery.error = "Could not read delivery state"
        await ui.step()
        assert details.size.height == 1 and details.has_class("-attention")
        assert "Delivery unavailable" in str(details.title)
        assert composer.value == "Untouched draft"
        assert history.status == "none"
        assert delivery.delivery.dismissed_historical_count == 5


async def test_live_activity_stays_above_the_details_row_and_the_draft_survives(workspace):
    async with workspace.app(size=(100, 32)) as ui:
        app, pilot = ui.textual
        view = ui.conversation
        details = view.query_one(SessionDetails)
        activity = view.query_one(TurnActivity)
        view.native_history_status = "none"
        view.busy_count = 1
        view.turns.start_client()
        view.prompt.text = "Keep this unsent draft"
        for ansi, size in ((False, (100, 32)), (True, (76, 26))):
            app.ansi_color = ansi
            app.refresh_css()
            await ui.resize(*size)
            for collapsed in (True, False):
                details.collapsed = collapsed
                for status in ("Thinking…", "Writing response…", "Calling tool: read"):
                    view.turns.describe(status)
                    await ui.step()
                    assert activity.region.bottom <= details.region.y, (
                        "Live activity must precede metadata, not be displaced by its divider", ansi)
                    assert activity in app.screen._compositor.visible_widgets
                    row = ui.painted(activity).splitlines()[0]
                    assert status in row, (ansi, collapsed, row)
                    assert not details.styles.border_top[0], (ansi, collapsed, details.styles.border_top)
                    if collapsed:
                        assert details.size.height == 1
                    assert activity.region.bottom <= view.throbber.region.y
                    assert view.prompt.text == "Keep this unsent draft"
