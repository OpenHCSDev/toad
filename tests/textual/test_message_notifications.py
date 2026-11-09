"""Visible notification lines consume typed Core outcomes; hidden views discard them.

Painting cases use controlled replies after retiring the shared observer's interest.
The live subscription/return journey is exercised in test_channel_updates_and_returns.
"""

from dataclasses import replace

from agent_comms.coordination.errors import ReloadRequired
from agent_comms.messaging.frozen_recipient import FrozenRecipient
from agent_comms.messaging.message_notification import MessageNotification
from agent_comms.messaging.notification_progress import (
    CompletedProgress,
    ConsumingProgress,
    IgnoredProgress,
    SendingProgress,
    ShownToModelProgress,
    UnrecordedProgress,
)
from agent_comms.ui_model.observation import (
    NotificationsObserved,
    NotificationsReload,
    NotificationsUnreadable,
    UnreadableHistory,
)

from toad.notification_status import CheckedNotifications
from toad.widgets.channels_sidebar import ChannelsSidebar
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
        outcomes = self.answer(request.operation.references)
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
    bar = app.screen.query_one(ChannelsSidebar)
    assert not bar.collapsed
    assert await pilot.click(bar.query_one(SideBarToggle))
    await ui.until(lambda: bar.collapsed, why="the channels sidebar collapsed")
    await ui.step()
    history = chat.message_history
    await ui.until(lambda: not history.undrawn and history.state.accepts_source_work
                   and history.visible_fragments(),
                   why="the channel's history read and on screen")
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
        assert 0 < len(request.operation.references) <= len(on_screen) < 30
        assert set(request.operation.references) <= on_screen
        await notifications.publish(ui, chat)
        await ui.until_shows(newest_status(chat).title)
        assert newest_status(chat).working
        # Held messages bring up the channel's queue line, as a DM's, so click the newest status drawn now.
        await ui.click("▶ Sent", occurrence=ui.visible_text().count("▶ Sent") - 1)
        await ui.until_shows("waiting-9: Sent")
        opened = history.visible_fragments()[-1].shown
        assert opened.details_open
        assert opened.status.details[0][0].text == "active"
        assert opened.status.details[0][1].text.startswith(": Sent")


async def test_a_read_whose_display_cut_is_gone_reads_its_page_again(workspace):
    CommsChatView = await open_comms_channel(workspace)
    notifications = Notifications()
    async with workspace.app(size=(110, 40)) as ui:
        await ui.open_channel("#comms", actor="peer")
        chat = ui.app.screen.query_one(CommsChatView)
        await settled(ui, chat)
        notifications.state = ConsumingProgress(0)
        await notifications.publish(ui, chat)
        await ui.until_shows(newest_status(chat).title)
        answered = newest_status(chat)
        access = ui.app.coordination_access
        history = chat.message_history
        request = access.notification_views[history.notification_view]
        observed_before = history.page_source.revision
        access.notifications_reload(
            NotificationsReload(access.revision, request, ReloadRequired("the display cut is gone")),
            access.observation.observed())
        await ui.until(lambda: history.page_source.revision is not observed_before,
                       why="the page was read afresh")
        # What it already showed stays on screen meanwhile.
        assert newest_status(chat) == answered


async def test_the_line_follows_typed_state_and_read_errors_without_new_messages(workspace):
    CommsChatView = await open_comms_channel(workspace)
    notifications = Notifications()
    async with workspace.app(size=(110, 40)) as ui:
        await ui.open_channel("#comms", actor="peer")
        chat = ui.app.screen.query_one(CommsChatView)
        await settled(ui, chat)
        notifications.state = ConsumingProgress(0)
        await notifications.publish(ui, chat)
        await ui.until_shows(newest_status(chat).title)
        assert newest_status(chat).working
        notifications.state = IgnoredProgress(ShownToModelProgress(0))
        await notifications.publish(ui, chat)
        await ui.until_shows(newest_status(chat).title)
        assert not newest_status(chat).working
        access = ui.app.coordination_access
        request = access.notification_views[chat.message_history.notification_view]
        error = UnreadableHistory.capture(OSError("fixture busy database"))
        answered = newest_status(chat)
        access.notifications_unreadable(NotificationsUnreadable(access.revision, request, error), access.observation.observed())
        await ui.step()
        # A failed read never hides an answer already shown; the next answer replaces it.
        assert newest_status(chat) == answered
        await ui.until_shows(answered.title)
        notifications.state = CompletedProgress(ShownToModelProgress(0))
        await notifications.publish(ui, chat)
        await ui.until_shows(newest_status(chat).title)


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
        view.notifications_observed(notifications.answer(request.operation.references))
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
        await ui.until_shows(newest_status(chat).title)
        notifications.recorded = False
        await notifications.publish(ui, chat)
        await ui.until_shows(newest_status(chat).title)
        assert newest_status(chat).notifications == ()


async def test_a_status_of_the_same_height_repaints_its_rows_without_measuring_the_page(workspace):
    """Seen, working and answered are one line each: changing between them repaints that
    line in its measured box. Opening the details changes the height and measures again."""
    CommsChatView = await open_comms_channel(workspace)
    notifications = Notifications()
    async with workspace.app(size=(110, 40)) as ui:
        await ui.open_channel("#comms", actor="peer")
        chat = ui.app.screen.query_one(CommsChatView)
        history = chat.message_history
        await settled(ui, chat)
        notifications.state = ConsumingProgress(0)
        await notifications.publish(ui, chat)
        newest = history.visible_fragments()[-1]
        page = history.page_holding(newest.key)
        measured = page._fragment_slots

        notifications.state = IgnoredProgress(ShownToModelProgress(0))
        await notifications.publish(ui, chat)
        await ui.until_shows(newest_status(chat).title)
        assert page._fragment_slots is measured, "a same-height status measured the page again"

        history.show_details(page, newest, newest.shown.toggled())
        await ui.until(lambda: newest.shown.details_open, why="the details opened")
        # The taller rows come from the render processes; the page measures again when they land.
        await ui.until(lambda: page._fragment_slots is not measured, why="a taller status measured again")


async def test_a_reread_or_resubscribed_message_starts_from_its_known_answer(workspace):
    """Scrolling re-reads pages and changes the subscribed set. A message whose answer is
    known keeps showing it: a re-read fragment is built with it and a new subscription is
    answered from it at once, so "Checking" never replaces a known answer."""
    from agent_comms.messaging.notification_reads import LiveNotificationRead
    from agent_comms.ui_model.observation import ReadNotifications

    from toad.notification_status import UncheckedNotifications

    CommsChatView = await open_comms_channel(workspace)
    notifications = Notifications()
    async with workspace.app(size=(110, 40)) as ui:
        await ui.open_channel("#comms", actor="peer")
        chat = ui.app.screen.query_one(CommsChatView)
        history = chat.message_history
        await settled(ui, chat)
        notifications.state = ConsumingProgress(0)
        await notifications.publish(ui, chat)
        newest = history.visible_fragments()[-1]
        answered = newest.shown.status
        access = ui.app.coordination_access
        source = chat.queue_source

        # The scope WireSource.read builds for a re-read page is the view's own scope.
        scope = ReadNotifications(str(source.root), LiveNotificationRead(()),
                                  display=newest.notification_identity)
        assert access.notification_status(scope, newest.notification_references) == answered

        # A subscription for a different visible set is answered from what is known.
        view = history.notification_view
        request = access.notification_views[view]
        shifted = replace(request, operation=replace(
            request.operation, references=request.operation.references[-1:]))
        assert access.known_outcomes(shifted), "the known answer was dropped when the set changed"
        access.show_notifications(view, shifted)
        await ui.step()
        assert newest.shown.status == answered
        assert newest.shown.status != UncheckedNotifications()
