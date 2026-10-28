"""Textual-facing: a notification feedback title (a collapsible widget) keeps its layout when only details or errors change."""

from dataclasses import replace

from agent_comms.audience_manifest import FrozenRecipient
from agent_comms.notification_progress import CompletedProgress, ConsumingProgress, ShownToModelProgress
from agent_comms.presentation import MessageNotification
from agent_comms.thread_identity import RecordedThreadIncarnation

from toad.notification_status import CheckedNotifications, UnavailableNotifications
from toad.widgets.message_notifications import MessageNotifications


async def test_changed_details_and_errors_keep_the_title_layout_but_changed_summaries_publish(workspace):
    workspace.thread("source")
    feedback = MessageNotifications()
    async with workspace.app(size=(90, 30), resume="source") as ui:
        app, pilot = ui.textual
        # Sent-message feedback lives inside a conversation, which owns its project path.
        await ui.conversation.mount(feedback)
        # The state Core shows while the recipient works on the message its context took in.
        responding = MessageNotification(FrozenRecipient("peer", "peer"), "owner", ConsumingProgress(1))
        feedback.show(CheckedNotifications((responding,)))
        await ui.step()
        title = feedback.query_one("CollapsibleTitle")
        assert await pilot.click(title)
        await ui.step()
        assert not feedback.collapsed
        # The first human reader changes the summary's Read count, so the title publishes.
        read_by = replace(responding, displayed_to=(RecordedThreadIncarnation("reader", 1.0),))
        feedback.show(CheckedNotifications((read_by,)))
        await ui.step()
        assert str(feedback.title) == MessageNotification.summary((read_by,))
        assert str(feedback.title) != MessageNotification.summary((responding,))
        await ui.until(lambda: "Read by reader" in " ".join(ui.painted(feedback).split()), why="the first reader")
        # Another viewer of an already-read row changes only the details: same count, same title.
        before = title._layout_updates
        reread = replace(read_by, displayed_to=(RecordedThreadIncarnation("other-reader", 2.0),))
        feedback.show(CheckedNotifications((reread,)))
        await ui.step()
        assert title._layout_updates == before
        await ui.until(lambda: "Read by other-reader" in " ".join(ui.painted(feedback).split()), why="the changed details")
        assert str(feedback.title) == MessageNotification.summary((reread,)) == MessageNotification.summary((read_by,))
        assert feedback.has_class("-working")
        completed = replace(reread, state=CompletedProgress(ShownToModelProgress(1)))
        feedback.show(CheckedNotifications((completed,)))
        await ui.step()
        assert str(feedback.title) == MessageNotification.summary((completed,))
        assert str(feedback.title) != MessageNotification.summary((reread,))
        assert not feedback.has_class("-working")
        feedback.show(UnavailableNotifications("First read error"))
        await ui.step()
        before = title._layout_updates
        feedback.show(UnavailableNotifications("Changed read error"))
        await ui.step()
        assert title._layout_updates == before
        await ui.until(lambda: "Changed read error" in " ".join(ui.painted(feedback).split()), why="the changed error")
        assert feedback.has_class("-unavailable")
