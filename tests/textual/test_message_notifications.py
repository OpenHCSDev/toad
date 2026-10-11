"""Textual-facing: notification feedback widgets under chat rows (collapsible titles, details, row styles, hidden screens)."""

import asyncio
from threading import Event, get_ident
from unittest.mock import patch

from agent_comms.audience_manifest import FrozenRecipient
from agent_comms.presentation import MessageNotification
from textual.app import App
from textual.screen import Screen

from support.textual_steps import refresh_chat

PEERS = 44


class Notifications:
    """What the stand-in Core read reports, and how often and where it was asked."""

    def __init__(self, loop_thread):
        self.loop_thread = loop_thread
        self.calls = []
        self.state, self.priority, self.busy, self.failure = "Checking relevance…", 0, True, False
        self.gate, self.entered = Event(), Event()
        self.gate.set()

    def read(self, batch):
        assert get_ident() != self.loop_thread, "notifications were read on the UI thread"
        self.calls.append(tuple(m.view_key for m in batch))
        self.entered.set()
        assert self.gate.wait(10), "fixture release missing"
        if self.failure:
            raise OSError("fixture busy database")
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


def newest_feedback(chat):
    from toad.widgets.message_notifications import MessageNotifications

    return next(w.query_one(MessageNotifications) for m, w in reversed(chat.message_history.rows)
                if m.view_key in chat.message_history.painted_keys())


async def settled(ui, chat):
    history = chat.message_history
    await ui.until(lambda: history.reader is not None and not history.reader.source.loading
                   and history.state.accepts_source_work, why="the channel's history read")
    await ui.step()
    chat._refresh_notifications()
    await ui.until(lambda: chat._notification_task is not None and chat._notification_task.is_finished,
                   why="the notification batch")


async def test_feedback_shows_the_core_state_of_the_painted_rows_in_one_bounded_batch(workspace):
    notifications, CommsChatView = await open_comms_channel(workspace)
    with reading(workspace, notifications):
        async with workspace.app(size=(110, 40)) as ui:
            await ui.open_channel("#comms", actor="peer")
            chat = ui.textual[0].screen.query_one(CommsChatView)
            await settled(ui, chat)
            feedback = newest_feedback(chat)
            assert str(feedback.title).startswith("Checking relevance… (1)"), feedback.title
            assert 0 < len(notifications.calls[-1]) <= len(chat.message_history.rows) <= 120
            assert set(notifications.calls[-1]) <= {m.view_key for m, _ in chat._visible_notification_rows()}
            await ui.textual[1].click(feedback.query_one("CollapsibleTitle"))
            await ui.step()
            assert not feedback.collapsed and "active: Checking relevance…" in str(feedback.details.render())


async def test_feedback_follows_changing_state_and_errors_without_new_messages(workspace):
    notifications, CommsChatView = await open_comms_channel(workspace)
    with reading(workspace, notifications):
        async with workspace.app(size=(110, 40)) as ui:
            await ui.open_channel("#comms", actor="peer")
            chat = ui.textual[0].screen.query_one(CommsChatView)
            await settled(ui, chat)
            feedback = newest_feedback(chat)
            feedback.parent.scroll_visible(animate=False, immediate=True, top=True)
            await ui.step()
            # Same bus revision, changed native lifecycle: the observation timer must refresh.
            notifications.state, notifications.priority, notifications.busy = "Responding…", 1, True
            await ui.until(lambda: "Responding…" in str(feedback.title), seconds=15, why="the new state")
            notifications.state, notifications.priority, notifications.busy = "Checked — no response", 2, False
            await ui.until(lambda: str(feedback.title).startswith("Checked — no response (1)"), seconds=15,
                           why="the finished state")
            notifications.failure = True
            await ui.until(lambda: "unavailable" in str(feedback.title), seconds=15, why="the failure")
            assert "fixture busy database" in str(feedback.details.render())
            notifications.failure, notifications.state = False, "Responded"
            await ui.until(lambda: str(feedback.title).startswith("Responded (1)"), seconds=15, why="recovery")


async def test_one_batch_at_a_time_and_a_hidden_view_discards_its_result_and_stops_reading(workspace):
    notifications, CommsChatView = await open_comms_channel(workspace)
    with reading(workspace, notifications):
        async with workspace.app(size=(110, 40)) as ui:
            app = ui.textual[0]
            await ui.open_channel("#comms", actor="peer")
            chat = app.screen.query_one(CommsChatView)
            await settled(ui, chat)
            notifications.entered.clear()
            notifications.gate.clear()
            chat._refresh_notifications()
            await ui.until(notifications.entered.is_set, why="a read in flight")
            count = len(notifications.calls)
            chat._refresh_notifications()
            chat._refresh_notifications()
            assert len(notifications.calls) == count
            await app.push_screen(Screen())
            notifications.gate.set()
            await ui.until(lambda: chat._notification_task.is_finished, why="the in-flight read to end")
            for _ in range(3):
                chat._refresh_notifications()
                await refresh_chat(chat)
            assert len(notifications.calls) == count
            app.pop_screen()
            await ui.step()


async def test_markdown_rows_use_the_same_feedback_and_an_empty_result_says_so(workspace):
    from toad.widgets.message_notifications import MessageNotifications

    notifications, CommsChatView = await open_comms_channel(workspace)
    notifications.state, notifications.busy = "Responded", False
    with reading(workspace, notifications):
        async with workspace.app(size=(110, 40)) as ui:
            await ui.open_channel("#comms", actor="peer")
            chat = ui.textual[0].screen.query_one(CommsChatView)
            await settled(ui, chat)
            await chat.message_history.toggle_style()
            await ui.step()
            chat._refresh_notifications()
            await ui.until(lambda: chat._notification_task.is_finished, why="the Markdown batch")
            row = chat.message_history.rows[-1][1]
            assert not isinstance(row.read_ack_widget(), MessageNotifications)
            assert "Responded" in str(row.query_one(MessageNotifications).title)
            row.query_one(MessageNotifications).show_result(())
            assert "No recorded" in str(row.query_one(MessageNotifications).title)
