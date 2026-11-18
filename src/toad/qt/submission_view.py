"""Qt's answers to the shared `SubmissionView`, for every Qt view a composer submits from:
the channel tab and the thread views. A refused or unknown send restores the draft and
says why; sends run side by side on the application's operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from toad.client.bus_submission import ConversationSubmission, SubmissionView
from toad.client.submission import MessageDestination


class QtSubmissionView(SubmissionView):
    @property
    def submission_composer(self):
        return self.composer

    def show_send_failure(self, text: str) -> None:
        self.composer.show_failure(text)

    composer_block: str = ""

    async def refresh_composer(self, read_only: bool) -> None:
        """Hold the composer with the destination's read-only reason, or release it."""
        self.composer_block = MessageDestination.read_only_reason if read_only else ""
        self.on_composer("hold", lambda composer: composer.hold(self.composer_block))

    def draws_user_message(self, reference) -> bool:
        return self.message_history.draws(reference)

    def record_input(self, text: str) -> None:
        """The Qt composer recalls no earlier input, so there is no history to keep."""

    def run_submission(self, send: Callable[[], Awaitable[None]]) -> None:
        self.app.run_operation(ConversationSubmission, send)

    def submissions_changed(self) -> None:
        if self.composer is not None:
            self.composer.sync_queue()
