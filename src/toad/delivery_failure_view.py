"""The concrete compose controls used by shared delivery-failure declarations."""


from abc import abstractmethod
from collections.abc import Awaitable, Callable
from functools import partial

from agent_comms.messaging.message_reference import MessageReference
from rich.text import Text as RichText
from textual import getters
from textual.content import Content
from textual.reactive import var
from textual.widget import Widget

from textual.worker import Worker

from toad.app_node import ToadNode
from toad.client.bus_submission import ConversationSubmission, SubmissionView
from toad.client.prompt_composer import ComposerStatus
from toad.client.submission import MessageDestination
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt
from toad.worker_group import InputHistoryRecord


class DeliveryFailureView(ComposerStatus, SubmissionView, ToadNode, Widget):
    """The composed input, status and delivery behavior shared by conversations.

    Sending never holds compose: a send waits in the view's submissions, shown above the
    composer, while the owner keeps typing. Only a read-only saved view holds compose."""

    prompt = getters.query_one(Prompt)
    feedback = getters.query_one(Flash)
    status: var[str | Content | RichText] = var("")
    thread_status: var[str | Content | RichText] = var("")
    """The thread's own status from its owner; a read-only block shows over it."""
    composer_block: var[str] = var("")
    """Why compose is held: a read-only saved view; empty when open."""

    @abstractmethod
    def draws_user_message(self, reference: MessageReference) -> bool: ...

    def compute_status(self) -> str | Content | RichText:
        return self.composed_status()

    async def refresh_composer(self, read_only: bool) -> None:
        """Draw compose from the caller's Core answer."""
        if not self.is_attached:
            return
        reason = MessageDestination.read_only_reason if read_only else ""
        area = self.prompt.prompt_text_area
        area.disabled = bool(reason)
        area.tooltip = reason or None
        self.composer_block = reason
        if not area.disabled and self.screen.focused is None:
            self.screen.set_focus(area)

    def delivery_unknown(self, description: str, body: str) -> None:
        """The request may have reached Core. The owner sees whether it landed in this view,
        so the draft comes back instead of waiting on an answer it cannot get."""
        self.prompt.restore_draft(body)
        self.feedback.flash(self.unknown_notice(description), style="error")

    def delivery_refused(self, description: str, body: str) -> None:
        self.prompt.restore_draft(body)
        self.feedback.flash(self.refusal_notice(description), style="error")

    def record_input(self, text: str) -> None:
        InputHistoryRecord.run_on(self, partial(self.input_histories.prompt.record, text))

    def run_submission(self, send: Callable[[], Awaitable[None]]) -> Worker[None]:
        return self.run_worker(send, group=ConversationSubmission.group)

    def submissions_changed(self) -> None:
        if (prompt := self.query_one_optional(Prompt)) is not None:
            prompt.sync_queue()
