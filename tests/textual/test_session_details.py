"""Textual-facing: the session details disclosure (a Textual Collapsible) takes one row when closed, a bounded height when open, and sits above the composer without moving the draft."""

import pytest
from textual.content import Content
from textual.screen import Screen
from textual.widgets import Input

from agent_comms.audience_manifest import FrozenRecipient
from agent_comms.messages import InfoKind, Message
from agent_comms.notification_progress import HarnessConsumedProgress
from agent_comms.presentation import MessageNotification
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.ui_model.delivery import ReadDeliveryView
from agent_comms.input_disposition import DeliveryOverview
from agent_comms.input_attempt import UnobservedInputDeliveryScope
from agent_comms.ui_model.status import ThreadStatusModel
from toad.line_blocks import NoticeRole
from toad.widgets.input_delivery import InputDeliveryBar
from toad.private_native_cursor import NoneCursorStatus
from toad.widgets.native_history import NativeHistory
from toad.widgets.session_details import SessionDetails


@pytest.mark.parametrize("ansi", [False, True], ids=["rgb", "ansi"])
async def test_details_are_one_row_until_opened_and_then_bounded(workspace, ansi):
    notifications = tuple(MessageNotification(
        FrozenRecipient("owner", "owner"), "peer", HarnessConsumedProgress(), message=Message("peer", "#comms", f"Notice {index}: " + "body " * 30,
                                                 InfoKind, seq=index + 1),
    ) for index in range(30))
    state = ThreadPresentation("owner", "●", "Ready", notifications=notifications)
    history = NativeHistory()
    history.status = NoneCursorStatus
    delivery = InputDeliveryBar()
    delivery.delivery = ReadDeliveryView(DeliveryOverview(
        inputs=(), historical_count=0, dismissed_historical_count=5, historical_inputs=(),
        current_scope=UnobservedInputDeliveryScope,
    ))
    details = SessionDetails(history=history, delivery=delivery)
    row = ThreadStatusModel.known("owner", state)

    class Example(Screen):
        def compose(self):
            yield details
            yield Input("Untouched draft", id="composer")

    # Wide enough for the whole collapsed summary, which now also names the latest inbound message.
    async with workspace.app(size=(140, 30)) as ui:
        app, pilot = ui.textual
        app.ansi_color = ansi
        await app.push_screen(Example())
        details.show(row.with_delivery(delivery.delivery))
        await ui.until(lambda: details.size.height, why="the details row")
        composer = app.screen.query_one(Input)
        assert details.collapsed and details.size.height == 1
        frame = ui.visible_text()
        # SessionDetails.summary_title owns the live caption; there is no fixed one.
        title = details.title.plain
        assert title and title in frame
        assert "30 recent" in frame and "5 notices" in frame
        assert "Notice 0" not in frame and "Bus history:" not in frame
        assert composer.region.y == details.region.bottom

        assert await pilot.click(details.query_one("CollapsibleTitle"))
        await ui.step()
        assert not details.collapsed and details.size.height <= details.DETAIL_ROWS + 1
        assert "Recent incoming messages" in str(details.notifications.render())
        history.scroll_visible(animate=False, immediate=True)
        await ui.step()
        assert history in app.screen._compositor.visible_widgets
        assert "no verified input" in str(history.render())
        details.collapsed = True
        delivery.delivery = delivery.delivery.failed(OSError("Could not read delivery state"))
        details.show(row.with_delivery(delivery.delivery))
        await ui.step()
        assert details.size.height == 1
        assert details.title.is_same(Content.styled(details.title.plain, app.colours.style(NoticeRole)))
        assert "Delivery unavailable" in str(details.title)
        assert composer.value == "Untouched draft"
        assert history.status is NoneCursorStatus
        assert delivery.delivery.notices == 5

