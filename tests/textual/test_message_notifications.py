"""Visible notification lines consume typed Core outcomes; hidden views discard them.

Painting cases use controlled replies after retiring the shared observer's interest.
The live subscription/return journey is exercised in test_channel_updates_and_returns.
"""

from agent_comms.audience_manifest import FrozenRecipient
from agent_comms.notification_progress import (
    CompletedProgress, ConsumingProgress, IgnoredProgress, SendingProgress,
    ShownToModelProgress, UnrecordedProgress,
)
from agent_comms.presentation import MessageNotification
from agent_comms.ui_model.observation import NotificationsObserved, NotificationsUnreadable, UnreadableHistory
from toad.notification_status import CheckedNotifications
from toad.widgets.side_bar import SideBar, SideBarToggle

PEERS = 44


class Notifications:
    """The typed outcome a controlled Core reply supplies to the real view."""

    def __init__(self):
        self.state = SendingProgress(0)
        self.recorded = True

    def answer(self, references):
        return {(reference.seq, reference.message_id): (
            MessageNotification(FrozenRecipient("active", "active"), "sender", self.state),
            *(MessageNotification(FrozenRecipient(f"waiting-{n}", f"waiting-{n}"),
                                  "sender", UnrecordedProgress()) for n in range(PEERS)),
        ) if self.recorded else () for reference in references}

    async def publish(self, ui, chat):
        view = chat.message_history.notification_view
        access = ui.app.coordination_access
        request = access.notification_views[view]
        outcomes = self.answer(request.references)
        expected, = CheckedNotifications.for_references(
            chat.message_history.visible_fragments()[-1].notification_references, outcomes)
        access.notifications_observed(NotificationsObserved(access.revision, request, outcomes), access.observation.observed())
        await ui.until(lambda: newest_status(chat) == expected,
                       why="the controlled notification reply drawn")
        await ui.step()


async def open_comms_channel(workspace):
    from toad.widgets.comms_chat import CommsChatView

    workspace.thread("peer", "comms", running=True)
    for n in range(30):
        workspace.comms.messaging.send("peer", "#comms", f"Test {n}: " + "body " * 12)
    return CommsChatView


def newest_status(chat):
    return chat.message_history.visible_fragments()[-1].shown.status


async def settled(ui, chat):
    # The channels sidebar takes 40% of the terminal and ellipsizes the summary's totals;
    # collapse it through its real toggle so the conversation gets the width.
    app, pilot = ui.textual
    bar = app.screen.query_one("#channels-sidebar", SideBar)
    assert not bar.collapsed
    assert await pilot.click(bar.query_one(SideBarToggle))
    await ui.until(lambda: bar.collapsed, why="the channels sidebar collapsed")
    await ui.step()
    history = chat.message_history
    await ui.until(lambda: not history.undrawn and history.state.accepts_source_work,
                   why="the channel's history read")
    await ui.step()
    await ui.until(lambda: history.notification_view in ui.app.coordination_access.notification_views,
                   why="the visible references subscribed to Core")
    # Keep the actual read process available for acquired work; retire automatic
    # interest before supplying controlled replies at the view's public callback.
    await ui.app.coordination_access.stop_observing()


async def test_visible_references_are_bounded_and_typed_outcomes_paint_their_details(workspace):
    CommsChatView = await open_comms_channel(workspace)
    notifications = Notifications()
    async with workspace.app(size=(110, 40)) as ui:
        await ui.open_channel("#comms", actor="peer")
        chat = ui.app.screen.query_one(CommsChatView)
        history = chat.message_history
        await settled(ui, chat)
        request = ui.app.coordination_access.notification_views[history.notification_view]
        on_screen = {reference for fragment in history.visible_fragments()
                     for reference in fragment.notification_references}
        assert 0 < len(request.references) <= len(on_screen) < 30
        assert set(request.references) <= on_screen
        await notifications.publish(ui, chat)
        await ui.until_shows("Delivered 45/45 · Consumed 0/45 · Read 0/45")
        assert newest_status(chat).working
        await ui.click("▶ Sent", occurrence=len(on_screen) - 1)
        await ui.until_shows("waiting-9: Sent")
        opened = history.visible_fragments()[-1].shown
        assert opened.details_open
        assert opened.status.details[0][0].text == "active"
        assert opened.status.details[0][1].text.startswith(": Sent")


async def test_the_line_follows_typed_state_and_read_errors_without_new_messages(workspace):
    CommsChatView = await open_comms_channel(workspace)
    notifications = Notifications()
    async with workspace.app(size=(110, 40)) as ui:
        await ui.open_channel("#comms", actor="peer")
        chat = ui.app.screen.query_one(CommsChatView)
        await settled(ui, chat)
        notifications.state = ConsumingProgress(0)
        await notifications.publish(ui, chat)
        await ui.until_shows("Answering 1 · Delivered 45/45 · Consumed 1/45 · Read 0/45")
        assert newest_status(chat).working
        notifications.state = IgnoredProgress(ShownToModelProgress(0))
        await notifications.publish(ui, chat)
        await ui.until_shows("Seen, not answering 1 · Delivered 45/45 · Consumed 1/45 · Read 0/45")
        assert not newest_status(chat).working
        access = ui.app.coordination_access
        request = access.notification_views[chat.message_history.notification_view]
        error = UnreadableHistory.capture(OSError("fixture busy database"))
        access.notifications_unreadable(NotificationsUnreadable(access.revision, request, error), access.observation.observed())
        await ui.until_shows("▶ Notification status unavailable")
        assert "fixture busy database" in newest_status(chat).error
        notifications.state = CompletedProgress(ShownToModelProgress(0))
        await notifications.publish(ui, chat)
        await ui.until_shows("▶ Answered · Delivered 45/45 · Consumed 1/45 · Read 0/45")


async def test_a_hidden_view_unsubscribes_and_discards_a_late_reply(workspace):
    CommsChatView = await open_comms_channel(workspace)
    notifications = Notifications()
    async with workspace.app(size=(110, 40)) as ui:
        owner = ui.selected_tab
        await ui.open_channel("#comms", actor="peer")
        chat = ui.app.screen.query_one(CommsChatView)
        await settled(ui, chat)
        await notifications.publish(ui, chat)
        history = chat.message_history
        view = history.notification_view
        request = ui.app.coordination_access.notification_views[view]
        before = {fragment.message.reference: fragment.shown.status
                  for fragment in history.fragments_in_range}
        await ui.select_tab(owner)
        assert view not in ui.app.coordination_access.notification_views
        notifications.state = CompletedProgress(ShownToModelProgress(0))
        view.notifications_observed(notifications.answer(request.references))
        await ui.step()
        assert view not in ui.app.coordination_access.notification_views
        assert {fragment.message.reference: fragment.shown.status
                for fragment in history.fragments_in_range} == before


async def test_markdown_uses_the_same_typed_line_and_an_empty_recorded_result(workspace):
    CommsChatView = await open_comms_channel(workspace)
    notifications = Notifications()
    notifications.state = CompletedProgress(ShownToModelProgress(0))
    async with workspace.app(size=(110, 40)) as ui:
        await ui.open_channel("#comms", actor="peer")
        chat = ui.app.screen.query_one(CommsChatView)
        await settled(ui, chat)
        await chat.message_history.toggle_style()
        await ui.step()
        await notifications.publish(ui, chat)
        await ui.until_shows("▶ Answered · Delivered 45/45 · Consumed 1/45 · Read 0/45")
        notifications.recorded = False
        await notifications.publish(ui, chat)
        await ui.until_shows("▶ No recorded notification result")
