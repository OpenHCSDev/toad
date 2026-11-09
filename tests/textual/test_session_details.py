"""Textual-facing: the session details disclosure (a Textual Collapsible) takes one row when closed, a bounded height when open, and sits above the composer without moving the draft."""

import pytest
from agent_comms.input_attempt import UnobservedInputDeliveryScope
from agent_comms.input_disposition import DeliveryOverview
from agent_comms.message_notification import MessageNotification
from agent_comms.messaging.frozen_recipient import FrozenRecipient
from agent_comms.messaging.messages import InfoKind, Message
from agent_comms.notification_progress import HarnessConsumedProgress
from agent_comms.transcript.transcripts import NotifiedThreadPresentation
from agent_comms.ui_model.delivery import ReadDeliveryView
from agent_comms.ui_model.status import ThreadStatusModel
from textual.content import Content
from textual.screen import Screen
from textual.widgets import Input

from toad.line_blocks import NoticeRole
from toad.private_native_cursor import NoneCursorStatus
from toad.widgets.input_delivery import InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.session_details import SessionDetails, SessionDetailsContents


@pytest.mark.parametrize("ansi", [False, True], ids=["rgb", "ansi"])
async def test_details_are_one_row_until_opened_and_then_bounded(workspace, ansi):
    notifications = tuple(MessageNotification(
        FrozenRecipient("owner", "owner"), "peer", HarnessConsumedProgress(0), message=Message("peer", "#comms", f"Notice {index}: " + "body " * 30,
                                                 InfoKind, seq=index + 1),
    ) for index in range(30))
    state = NotifiedThreadPresentation("owner", "●", "Ready", notifications=notifications)
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
        # Delivery's own words, not a copy of them. The title used to read "5 notices" for
        # five notices that were CLEARED, one phrase answering two questions (IDEN-1); it
        # now joins the parts delivery itself supplies.
        assert "30 recent" in frame
        assert delivery.delivery.parts() == ("5 earlier notices cleared",)
        for part in delivery.delivery.parts():
            assert part in frame
        # Asked of the owner. This read '"Bus history:" not in frame', a prefix that no
        # longer exists anywhere, so it would have passed with the detail on screen: a
        # negative assertion against a deleted string cannot fail.
        assert "Notice 0" not in frame
        assert NoneCursorStatus.label not in frame, "the collapsed row holds no history line"
        assert composer.region.y == details.region.bottom

        assert await pilot.click(details.query_one("CollapsibleTitle"))
        await ui.step()
        assert not details.collapsed and details.size.height <= SessionDetailsContents.DETAIL_ROWS + 1
        assert "Recent incoming messages" in str(details.notifications.render())
        history.scroll_visible(animate=False, immediate=True)
        await ui.step()
        assert history in app.screen._compositor.visible_widgets
        # The status's own label, not a fragment of it typed out here.
        assert str(history.render()) == NoneCursorStatus.label
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

