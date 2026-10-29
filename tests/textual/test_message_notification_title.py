"""Textual-facing: a notification feedback title (a collapsible widget) keeps its layout when only details or errors change."""

from dataclasses import replace

from agent_comms.audience_manifest import FrozenRecipient
from agent_comms.notification_progress import (
    CompletedProgress, ConsumingProgress, QueuedProgress, SentProgress, ShownToModelProgress,
)
from agent_comms.presentation import MessageNotification

from toad.notification_status import CheckedNotifications, UnavailableNotifications
from toad.widgets.message_notifications import MessageNotifications


async def test_changed_details_and_errors_keep_the_title_layout_but_changed_summaries_publish(workspace):
    workspace.thread("source")
    feedback = MessageNotifications()
    async with workspace.app(size=(90, 30), resume="source") as ui:
        app, pilot = ui.textual
        # Sent-message feedback lives inside a conversation, which owns its project path.
        await ui.conversation.mount(feedback)
        # Two agents: one works on the message its context took in, the other has it sent.
        responding = MessageNotification(FrozenRecipient("peer", "peer"), "owner", ConsumingProgress(1))
        waiting = MessageNotification(FrozenRecipient("waiting-peer", "waiting-peer"), "owner", SentProgress(1))
        feedback.show(CheckedNotifications((responding, waiting)))
        await ui.step()
        title = feedback.query_one("CollapsibleTitle")
        assert await pilot.click(title)
        await ui.step()
        assert not feedback.collapsed
        await ui.until(lambda: "waiting-peer: Sent" in " ".join(ui.painted(feedback).split()), why="the sent detail")
        before = title._layout_updates
        # Only the second agent's detail changes: the first row still leads, the counts hold.
        queued = replace(waiting, state=QueuedProgress(1))
        feedback.show(CheckedNotifications((responding, queued)))
        await ui.step()
        assert title._layout_updates == before
        await ui.until(lambda: "waiting-peer: Queued" in " ".join(ui.painted(feedback).split()), why="the changed detail")
        assert str(feedback.title) == MessageNotification.summary((responding, queued))
        assert str(feedback.title) == MessageNotification.summary((responding, waiting))
        assert feedback.has_class("-working")
        completed = replace(responding, state=CompletedProgress(ShownToModelProgress(1)))
        feedback.show(CheckedNotifications((completed, queued)))
        await ui.step()
        assert str(feedback.title) == MessageNotification.summary((completed, queued))
        assert str(feedback.title) != MessageNotification.summary((responding, queued))
        assert not feedback.has_class("-working")
        feedback.show(UnavailableNotifications("First read error"))
        await ui.step()
        before = title._layout_updates
        feedback.show(UnavailableNotifications("Changed read error"))
        await ui.step()
        assert title._layout_updates == before
        await ui.until(lambda: "Changed read error" in " ".join(ui.painted(feedback).split()), why="the changed error")
        assert feedback.has_class("-unavailable")
