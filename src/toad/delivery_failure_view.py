"""The concrete compose controls used by shared delivery-failure declarations."""


import asyncio
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path

from agent_comms.errors import (
    CommittedMessageError,
    HumanSendError,
    HumanSendRefusedError,
    RelationViolationError,
    RouteChangedError,
)
from agent_comms.message_reference import MessageReference
from rich.text import Text as RichText
from textual import getters
from textual.content import Content
from textual.reactive import var
from textual.widget import Widget

from toad.app_node import ToadNode
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt


class SendState:
    """Where this view's own human-message send stands; compose follows it."""

    reason = ""

    def drawn_in(self, view) -> bool:
        """Whether this send is now drawn in `view`, so compose can open again."""
        return False

    def abandoned(self, view: "DeliveryFailureView", body: str) -> None:
        """The send's own failure handling already answered; nothing is left pending."""


class NoSend(SendState):
    pass


class SendPending(SendState):
    reason = "Send pending; do not retry"

    def abandoned(self, view: "DeliveryFailureView", body: str) -> None:
        """The send failed before its request left: nothing was sent, compose reopens."""
        view.delivery_refused("the send failed before it left this machine", body)


@dataclass(frozen=True)
class SentUndrawn(SendState):
    root: Path
    sent: MessageReference

    @property
    def reason(self) -> str:
        return f"Sent {self.root}/{self.sent.seq}/{self.sent.message_id}; waiting to be drawn, do not retry"

    def drawn_in(self, view) -> bool:
        return view.draws_user_message(self.sent)


class DeliveryFailureView(ToadNode, Widget):
    """The composed input, status and delivery behavior shared by conversations."""

    prompt = getters.query_one(Prompt)
    feedback = getters.query_one(Flash)
    status: var[str | Content | RichText] = var("")
    thread_status: var[str | Content | RichText] = var("")
    """The thread's own status from its owner; a send or read-only block shows over it."""
    composer_block: var[str] = var("")
    """Why compose is held: this view's send, or a read-only saved view; empty when open."""

    @abstractmethod
    def draws_user_message(self, reference: MessageReference) -> bool: ...

    async def composer_read_only(self) -> bool:
        return False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._send_state: SendState = NoSend()

    @property
    def send_block_reason(self) -> str:
        """Why this view's own send holds compose; empty when it does not."""
        return self._send_state.reason

    def queue_evidence_changed(self) -> None:
        """An unbound delivery surface has no queue consumer to repaint."""

    def _enter_send_state(self, state: SendState) -> None:
        """The one place a send changes state; compose and the status line follow it."""
        self._send_state = state
        self.queue_evidence_changed()
        if self.is_attached:
            async def refresh() -> None:
                read_only = await self.composer_read_only()
                await self.refresh_composer(read_only)

            self.run_worker(refresh(), group="composer-access", exclusive=True)

    def compute_status(self) -> str | Content | RichText:
        return self.composer_block or self.thread_status

    async def refresh_composer(self, read_only: bool) -> None:
        """Draw compose from the caller's Core answer and the current send state."""
        if not self.is_attached:
            return
        reason = self.send_block_reason or ("Read-only saved view" if read_only else "")
        area = self.prompt.prompt_text_area
        area.disabled = bool(reason)
        area.tooltip = reason or None
        self.composer_block = reason
        if not area.disabled and self.screen.focused is None:
            self.screen.set_focus(area)

    async def submit_comms_message(self, root, conversation, body, current, present):
        """CLI transcripts and wire pages use the same Core-send checks."""
        from agent_comms.delivery_failure import delivery_failure

        if not body.strip():
            return
        if self.send_block_reason:
            self.feedback.flash(self.send_block_reason, style="error")
            return
        try:
            observed = await self.app.preparation.run_thread(self.app.coordination_access.observing, root)
            read_only = await self.app.preparation.run_thread(conversation.read_only, observed.core)
            await self.refresh_composer(read_only)
            if read_only:
                self.prompt.restore_draft(body)
                self.feedback.flash(self.status, style="error")
                return
            self._enter_send_state(SendPending())
            route_current = await self.app.preparation.run_thread(
                lambda: self.app.coordination_access.current(root)
            )
            if not route_current or not current():
                raise HumanSendRefusedError(RelationViolationError("Message route changed; reopen this view"))
            sent = await self.commit_user_message(observed, conversation.send_target(), body)
        except asyncio.CancelledError:
            self.delivery_refused("Cancelled before sending", body)
            raise
        except (HumanSendError, RouteChangedError) as error:
            delivery_failure(error).present(self, body)
            return
        except Exception:
            # An unexpected failure still fails loudly; it never leaves compose held by a
            # send that is no longer running.
            self._send_state.abandoned(self, body)
            raise
        if sent is None:
            return
        await present(sent)

    async def commit_user_message(self, observed, target, body):
        task = asyncio.create_task(asyncio.to_thread(observed.send_user_message, target, body))
        try:
            sent = await asyncio.shield(task)
        except asyncio.CancelledError:
            self.delivery_unknown("the send was cancelled while it may still be writing", body)
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
            return None
        except CommittedMessageError as error:
            sent = error.record.reference
        except Exception:
            # The request left: Core may have published it. Raise for the log, never hold compose.
            self.delivery_unknown("its reply could not be read", body)
            raise
        self._enter_send_state(SentUndrawn(observed.root, sent))
        return sent

    def settle_user_message(self) -> None:
        """Enable compose only when the sent message is drawn."""
        if self._send_state.drawn_in(self):
            self._enter_send_state(NoSend())

    def delivery_unknown(self, description: str, body: str) -> None:
        """The request may have reached Core. The owner sees whether it landed in this view,
        so compose reopens with the draft instead of locking on an answer it cannot get."""
        self.prompt.restore_draft(body)
        self._enter_send_state(NoSend())
        self.feedback.flash(
            f"Send outcome unknown: {description}. Check this conversation before resending.",
            style="error")

    def delivery_refused(self, description: str, body: str) -> None:
        self.prompt.restore_draft(body)
        self._enter_send_state(NoSend())
        self.feedback.flash(f"Send failed: {description}", style="error")
