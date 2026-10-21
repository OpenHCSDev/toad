"""The concrete compose controls used by shared delivery-failure declarations."""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_comms.acp_extension import UnknownDeliveryFailure
from agent_comms.errors import HumanClaimBlockedError, HumanInitialUnknownError
from agent_comms.messages import Message
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

    @property
    def reason(self) -> str:
        return ""

    def drawn_in(self, view: DeliveryFailureView) -> bool:
        """Whether this send is now drawn in `view`, so compose can open again."""
        return False

    async def present(self, accepted: Callable[[Message], Awaitable[object]]) -> None:
        """An unconfirmed send has no accepted message to present."""


class NoSend(SendState):
    pass


class SendPending(SendState):
    @property
    def reason(self) -> str:
        return "Send pending; do not retry"


@dataclass(frozen=True)
class SentUndrawn(SendState):
    root: Path
    sent: Message

    @property
    def reason(self) -> str:
        return f"Sent {self.root}/{self.sent.seq}/{self.sent.message_id}; waiting to be drawn, do not retry"

    def drawn_in(self, view: DeliveryFailureView) -> bool:
        return view.draws_user_message(self.sent)

    async def present(self, accepted: Callable[[Message], Awaitable[object]]) -> None:
        await accepted(self.sent)


@dataclass(frozen=True)
class SendBlocked(SendState):
    description: str

    @property
    def reason(self) -> str:
        return f"Send blocked: {self.description}"


@dataclass(frozen=True)
class SendUnknown(SendState):
    failure: UnknownDeliveryFailure

    @property
    def reason(self) -> str:
        failure = self.failure
        return (
            f"Send UNKNOWN {failure.wire_root_id}/{failure.wire_seq}/{failure.message_id}: "
            f"{failure.description}; inspect the bus, do not retry"
        )


class DeliveryFailureView(ToadNode, Widget):
    """The composed input, status and delivery behavior shared by conversations."""

    prompt = getters.query_one(Prompt)
    status: var[str | Content | RichText] = var("")

    @abstractmethod
    def draws_user_message(self, message: Message) -> bool: ...

    async def composer_read_only(self) -> bool:
        """Native and CLI sessions compose to their exact thread, not a saved channel."""
        return False

    def flash(
        self,
        content: str | Content,
        *,
        duration: float | None = None,
        style: Literal["default", "warning", "error", "success"] = "default",
    ) -> None:
        """Show feedback in this view's composed flash control."""
        self.query_one(Flash).flash(content, duration=duration, style=style)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._send_state: SendState = NoSend()

    @property
    def send_block_reason(self) -> str:
        """Why this view's own send holds compose; empty when it does not."""
        return self._send_state.reason

    def _enter_send_state(self, state: SendState) -> None:
        """Delivery changes compose availability, never the user's draft."""
        self._send_state = state
        if self.is_attached:

            async def refresh() -> None:
                read_only = await self.composer_read_only()
                await self.refresh_composer(read_only)

            self.run_worker(refresh(), group="composer-access", exclusive=True)

    async def refresh_composer(self, read_only: bool, status: str = "") -> str:
        """Draw compose and return the reason from the same delivery decision."""
        reason = self.send_block_reason or ("Read-only saved view" if read_only else "")
        if not self.is_attached:
            return reason
        area = self.prompt.prompt_text_area
        area.disabled = bool(reason)
        area.tooltip = reason or None
        self.status = reason or status
        if not area.disabled and self.screen.focused is None:
            self.screen.set_focus(area)
        return reason

    async def submit_comms_message(self, root, conversation, body, current, present):
        """CLI transcripts and wire pages use the same Core-send checks."""
        if not body.strip():
            return
        async with self.app.coordination_access.transcripts.bind(root) as comms:
            read_only = await self.app.preparation.run_thread(
                conversation.read_only, comms
            )
        reason = await self.refresh_composer(read_only)
        if read_only:
            self.restore_user_message(body)
            self.flash(reason, style="error")
            return
        references = (
            self.app.coordination_access.observation.observed()
            .sidebar.observation.require_snapshot().references
        )
        await self.deliver_user_message(
            root, conversation.send_target(references).name, body, current, present
        )

    async def deliver_user_message(self, root, target, body, current, present):
        """One route check, write and failure path for CLI, DM and channel input."""
        from agent_comms.delivery_failure import delivery_failure
        from agent_comms.route_selection import root_is_current

        if self.send_block_reason:
            self.restore_user_message(body)
            self.flash(self.send_block_reason, style="error")
            return
        self._enter_send_state(SendPending())

        async def require_route():
            route_current = await self.app.preparation.run_thread(root_is_current, root)
            if not route_current or not current():
                raise ValueError("Message route changed; reopen this view")

        try:
            async with self.app.coordination_access.transcripts.bind(root) as comms:
                await require_route()
        except asyncio.CancelledError:
            self.delivery_refused("Cancelled before sending", body)
            raise
        except (HumanInitialUnknownError, HumanClaimBlockedError) as error:
            delivery_failure(error).present(self, body)
            return
        outcome = await self.commit_user_message(comms, target, body)
        await outcome.present(present)

    async def commit_user_message(self, comms, target, body):
        from agent_comms.delivery_failure import delivery_failure
        from agent_comms.route_selection import run_selected_write

        task = asyncio.create_task(
            asyncio.to_thread(
                run_selected_write,
                comms.root,
                comms.messaging.send_user_message,
                target,
                body,
                worktree=str(self.project_path),
            )
        )
        try:
            sent = await asyncio.shield(task)
        except asyncio.CancelledError:
            self.delivery_blocked(
                "Send cancelled while worker may still write; outcome UNKNOWN, inspect the bus, do not retry",
                body,
            )
            task.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )
            return self._send_state
        except (HumanInitialUnknownError, HumanClaimBlockedError) as error:
            delivery_failure(error).present(self, body)
            return self._send_state
        accepted = SentUndrawn(comms.root, sent)
        self._enter_send_state(accepted)
        return accepted

    def settle_user_message(self) -> None:
        """Enable compose only when the sent message is drawn."""
        if self._send_state.drawn_in(self):
            self._enter_send_state(NoSend())

    def restore_user_message(self, body: str) -> None:
        """Give this failed send back only while no newer draft owns the input."""
        if not self.prompt.text:
            self.prompt.text = body

    def delivery_unknown(self, failure: UnknownDeliveryFailure, body: str) -> None:
        self.restore_user_message(body)
        self._enter_send_state(SendUnknown(failure))
        self.flash(self.send_block_reason, style="error")

    def delivery_blocked(self, description: str, body: str) -> None:
        self.restore_user_message(body)
        self._enter_send_state(SendBlocked(description))
        self.flash(self.send_block_reason, style="error")

    def delivery_refused(self, description: str, body: str) -> None:
        self.restore_user_message(body)
        self._enter_send_state(NoSend())
        self.flash(f"Send failed: {description}", style="error")
