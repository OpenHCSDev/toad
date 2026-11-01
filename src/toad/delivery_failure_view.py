"""Compose and error presentation derived from the submission owner."""

from abc import abstractmethod

from agent_comms.messages import Message
from rich.text import Text as RichText
from textual import getters
from textual.content import Content
from textual.reactive import var
from textual.widget import Widget

from toad.app_node import ToadNode
from toad.conversation_submission import ConversationSubmissions
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt


class DeliveryFailureView(ToadNode, Widget):
    """Draw submission state; this widget owns no transport or send lifecycle."""

    submissions: ConversationSubmissions
    prompt = getters.query_one(Prompt)
    feedback = getters.query_one(Flash)
    status: var[str | Content | RichText] = var("")
    thread_status: var[str | Content | RichText] = var("")
    composer_block: var[str] = var("")

    @abstractmethod
    def contains_user_message(self, message: Message) -> bool: ...

    async def composer_read_only(self) -> bool:
        return False

    @property
    def send_block_reason(self) -> str:
        return self.submissions.send_block_reason

    def queue_evidence_changed(self) -> None:
        """An unbound delivery surface has no queue consumer to repaint."""

    def refresh_submission_state(self) -> None:
        self.queue_evidence_changed()
        if self.is_attached:
            async def refresh() -> None:
                await self.refresh_composer(await self.composer_read_only())

            self.run_worker(refresh(), group="composer-access", exclusive=True)

    def compute_status(self) -> str | Content | RichText:
        return self.composer_block or self.thread_status

    async def refresh_composer(self, read_only: bool) -> None:
        if not self.is_attached:
            return
        reason = self.send_block_reason or ("Read-only saved view" if read_only else "")
        area = self.prompt.prompt_text_area
        area.disabled = bool(reason)
        area.tooltip = reason or None
        self.composer_block = reason
        if not area.disabled and self.screen.focused is None:
            self.screen.set_focus(area)

    def delivery_refused(self, description: str, body: str) -> None:
        self.prompt.restore_draft(body)
        self.feedback.flash(f"Send failed: {description}", style="error")
