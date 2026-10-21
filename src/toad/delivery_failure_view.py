"""The concrete compose controls used by shared delivery-failure declarations."""

import asyncio
from dataclasses import dataclass

from agent_comms.errors import HumanClaimBlockedError, HumanInitialUnknownError


class SendState:
    """Where this view's own human-message send stands; compose follows it."""

    reason = ""

    def drawn_in(self, view) -> bool:
        """Whether this send is now drawn in `view`, so compose can open again."""
        return False


class NoSend(SendState):
    pass


class SendPending(SendState):
    reason = "Send pending; do not retry"


@dataclass(frozen=True)
class SentUndrawn(SendState):
    root: str
    sent: object

    @property
    def reason(self) -> str:
        return f"Sent {self.root}/{self.sent.seq}/{self.sent.message_id}; waiting to be drawn, do not retry"

    def drawn_in(self, view) -> bool:
        return view.draws_user_message(self.sent)


@dataclass(frozen=True)
class SendBlocked(SendState):
    description: str

    @property
    def reason(self) -> str:
        return f"Send blocked: {self.description}"


@dataclass(frozen=True)
class SendUnknown(SendState):
    failure: object

    @property
    def reason(self) -> str:
        failure = self.failure
        return (
            f"Send UNKNOWN {failure.wire_root_id}/{failure.wire_seq}/{failure.message_id}: "
            f"{failure.description}; inspect the bus, do not retry"
        )


class DeliveryFailureView:
    """Own human-message delivery and its compose/failure controls."""

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

    async def refresh_composer(self, read_only: bool, status: str = "") -> None:
        """Draw compose from the caller's Core answer and the current send state."""
        if not self.is_attached:
            return
        reason = self.send_block_reason or ("Read-only saved view" if read_only else "")
        area = self.prompt.prompt_text_area
        area.disabled = bool(reason)
        area.tooltip = reason or None
        self.status = reason or status
        if not area.disabled and self.screen.focused is None:
            self.screen.set_focus(area)

    async def submit_comms_message(self, root, conversation, body, current, present):
        """CLI transcripts and wire pages use the same Core-send checks."""
        if not body.strip():
            return
        async with self.app.coordination_access.transcripts.bind(root) as comms:
            read_only = await self.app.preparation.run_thread(
                conversation.read_only, comms
            )
        await self.refresh_composer(read_only)
        if read_only:
            self.restore_user_message(body)
            self.flash(self.status, style="error")
            return
        await self.deliver_user_message(
            root, conversation.send_target().name, body, current, present
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
        sent = await self.commit_user_message(comms, target, body)
        if sent is None:
            return
        await present(sent)

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
            return None
        except (HumanInitialUnknownError, HumanClaimBlockedError) as error:
            delivery_failure(error).present(self, body)
            return None
        self._enter_send_state(SentUndrawn(comms.root, sent))
        return sent

    def settle_user_message(self) -> None:
        """Enable compose only when the sent message is drawn."""
        if self._send_state.drawn_in(self):
            self._enter_send_state(NoSend())

    def restore_user_message(self, body: str) -> None:
        """Give this failed send back only while no newer draft owns the input."""
        if not self.prompt.text:
            self.prompt.text = body

    def delivery_unknown(self, failure, body: str) -> None:
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
