"""Textual-facing: a notification feedback title (a collapsible widget) keeps its layout when only details or errors change."""

from dataclasses import replace

from agent_comms.audience_manifest import FrozenRecipient
from agent_comms.presentation import MessageNotification
from textual.app import App

from toad.textual_colours import ThemedApp
from toad.widgets.message_notifications import MessageNotifications


class FeedbackApp(ThemedApp, App):
    def compose(self):
        yield MessageNotifications()


async def test_changed_details_and_errors_keep_the_title_layout_but_changed_summaries_publish():
    app = FeedbackApp()
    async with app.run_test(size=(90, 20)) as pilot:
        feedback = app.query_one(MessageNotifications)
        first = MessageNotification(FrozenRecipient("peer", "peer"), "Responding", "First outcome", 1, True)
        feedback.show_result((first,))
        await pilot.pause()
        title = feedback.query_one("CollapsibleTitle")
        await pilot.click(title)
        await pilot.pause()
        assert not feedback.collapsed
        before = title._layout_updates
        feedback.show_result((replace(first, detail="Updated outcome"),))
        await pilot.pause()
        assert title._layout_updates == before
        assert "Updated outcome" in str(feedback.details.render())
        assert "Responding (1)" in str(feedback.title) and feedback.has_class("-working")
        feedback.show_result((replace(first, state="Responded", busy=False),))
        await pilot.pause()
        assert "Responded (1)" in str(feedback.title) and not feedback.has_class("-working")
        feedback.show_error(OSError("First read error"))
        await pilot.pause()
        before = title._layout_updates
        feedback.show_error(OSError("Changed read error"))
        await pilot.pause()
        assert title._layout_updates == before
        assert "Changed read error" in str(feedback.details.render())
        assert feedback.has_class("-unavailable")
        assert app._exception is None
