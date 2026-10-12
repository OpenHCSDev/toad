"""Textual-facing: the notification line under each drawn chat message (its title, details, both styles, hidden screens)."""

import asyncio
from threading import Event, get_ident
from unittest.mock import patch

from agent_comms.audience_manifest import FrozenRecipient
from agent_comms.presentation import MessageNotification

from support.textual_steps import refresh_chat

PEERS = 44


class Notifications:
    """What the stand-in Core read reports, and how often and where it was asked."""

    def __init__(self, loop_thread):
        self.loop_thread = loop_thread
        self.calls = []
        self.state, self.priority, self.busy, self.failure = "Checking relevance…", 0, True, False
        self.recorded = True
        self.gate, self.entered = Event(), Event()
        self.gate.set()

    def read(self, batch):
        assert get_ident() != self.loop_thread, "notifications were read on the UI thread"
        self.calls.append(tuple(m.view_key for m in batch))
        self.entered.set()
        assert self.gate.wait(10), "fixture release missing"
        if self.failure:
            raise OSError("fixture busy database")
        if not self.recorded:
            return {}
        return {(m.seq, m.message_id): (
            MessageNotification(FrozenRecipient("active", "active"), self.state, "#comms message", self.priority, self.busy),
            *(MessageNotification(FrozenRecipient(f"waiting-{n}", f"waiting-{n}"), "Waiting for agent", "Not running", 4, False)
              for n in range(PEERS))) for m in batch}


def reading(workspace, notifications):
    """Core's notification read answers from `notifications` for the duration of the context."""
    return patch.object(type(workspace.comms.views), "message_notifications",
                        lambda _views, batch: notifications.read(batch))


async def open_comms_channel(workspace):
    from toad.widgets.comms_chat import CommsChatView

    workspace.thread("peer", "comms", running=True)
    for n in range(30):
        workspace.comms.messaging.send("peer", "#comms", f"Test {n}: " + "body " * 12)
    notifications = Notifications(get_ident())
    return notifications, CommsChatView


def newest_status(chat):
    """What the newest message on screen shows about its notifications."""
    return chat.message_history.visible_fragments()[-1].shown.status


async def checked(ui, chat):
    """Read the notifications of the messages on screen now and wait for the read."""
    history = chat.message_history
    await ui.until(lambda: history._notification_check is None or history._notification_check.is_finished,
                   why="the earlier notification read")
    history.check_notifications()
    await ui.until(lambda: history._notification_check is not None and history._notification_check.is_finished,
                   why="the notification read")


async def settled(ui, chat):
    history = chat.message_history
    await ui.until(lambda: not history.undrawn and history.state.accepts_source_work, why="the channel's history read")
    await ui.step()
    await checked(ui, chat)


async def test_the_line_shows_the_core_state_of_the_messages_on_screen_in_one_bounded_read(workspace):
    notifications, CommsChatView = await open_comms_channel(workspace)
    with reading(workspace, notifications):
        async with workspace.app(size=(110, 40)) as ui:
            await ui.open_channel("#comms", actor="peer")
            chat = ui.textual[0].screen.query_one(CommsChatView)
            history = chat.message_history
            await settled(ui, chat)
            await ui.until_shows("Checking relevance… (1) · Waiting for agent (44)")
            on_screen = {fragment.message.view_key for fragment in history.visible_fragments()}
            assert 0 < len(notifications.calls[-1]) <= len(on_screen) < 30
            assert set(notifications.calls[-1]) <= on_screen
            await ui.click("▶ Checking relevance…", occurrence=len(on_screen) - 1)
            # Opened, the line lists every recipient below it; the reader stays at the newest row.
            await ui.until_shows("waiting-9: Waiting for agent — Not running")
            opened = history.visible_fragments()[-1].shown
            assert opened.details_open and opened.status.details.startswith("active: Checking relevance… — #comms message")


async def test_the_line_follows_changing_state_and_errors_without_new_messages(workspace):
    notifications, CommsChatView = await open_comms_channel(workspace)
    with reading(workspace, notifications):
        async with workspace.app(size=(110, 40)) as ui:
            await ui.open_channel("#comms", actor="peer")
            chat = ui.textual[0].screen.query_one(CommsChatView)
            await settled(ui, chat)

            # The state of a delivery changes without a new message; the next observed change shows it.
            async def shown_after_refresh(text):
                await refresh_chat(chat)
                await checked(ui, chat)
                await ui.until_shows(text, seconds=15)

            notifications.state, notifications.priority, notifications.busy = "Responding…", 1, True
            await shown_after_refresh("▶ Responding… (1)")
            assert newest_status(chat).working
            notifications.state, notifications.priority, notifications.busy = "Checked — no response", 2, False
            await shown_after_refresh("▶ Checked — no response (1)")
            assert not newest_status(chat).working
            notifications.failure = True
            await shown_after_refresh("▶ Notification status unavailable")
            assert "fixture busy database" in newest_status(chat).details
            notifications.failure, notifications.state = False, "Responded"
            await shown_after_refresh("▶ Responded (1)")


async def test_one_read_at_a_time_and_a_hidden_view_discards_its_result_and_stops_reading(workspace):
    notifications, CommsChatView = await open_comms_channel(workspace)
    with reading(workspace, notifications):
        async with workspace.app(size=(110, 40)) as ui:
            app = ui.textual[0]
            owner = ui.selected_tab
            await ui.open_channel("#comms", actor="peer")
            chat = app.screen.query_one(CommsChatView)
            history = chat.message_history
            await settled(ui, chat)
            before = newest_status(chat)
            notifications.state = "Responded"
            notifications.entered.clear()
            notifications.gate.clear()
            history.check_notifications()
            await ui.until(notifications.entered.is_set, why="a read in flight")
            count = len(notifications.calls)
            history.check_notifications()
            history.check_notifications()
            assert len(notifications.calls) == count
            # Another tab is selected: the channel view is no longer the one shown.
            await ui.select_tab(owner)
            notifications.gate.set()
            await ui.until(lambda: history._notification_check.is_finished, why="the in-flight read to end")
            for _ in range(3):
                await refresh_chat(chat)
            assert len(notifications.calls) == count
            assert all(fragment.shown.status == before for fragment in history.wire_fragments
                       if fragment.shown.status.title != "Notification status not checked")


async def test_markdown_messages_show_the_same_line_and_an_empty_result_says_so(workspace):
    notifications, CommsChatView = await open_comms_channel(workspace)
    notifications.state, notifications.busy = "Responded", False
    with reading(workspace, notifications):
        async with workspace.app(size=(110, 40)) as ui:
            await ui.open_channel("#comms", actor="peer")
            chat = ui.textual[0].screen.query_one(CommsChatView)
            await settled(ui, chat)
            await chat.message_history.toggle_style()
            await ui.step()
            await checked(ui, chat)
            await ui.until_shows("▶ Responded (1)")
            notifications.recorded = False
            await checked(ui, chat)
            await ui.until_shows("▶ No recorded notification result")
