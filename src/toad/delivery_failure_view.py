"""The concrete compose controls used by shared delivery-failure declarations."""


import asyncio
from dataclasses import dataclass


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
        return (f"Send UNKNOWN {failure.wire_root_id}/{failure.wire_seq}/{failure.message_id}: "
                f"{failure.description}; inspect the bus, do not retry")


class DeliveryFailureView:
    """Own human-message delivery and its compose/failure controls."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._send_state: SendState = NoSend()

    @property
    def send_block_reason(self) -> str:
        """Why this view's own send holds compose; empty when it does not."""
        return self._send_state.reason

    def _enter_send_state(self, state: SendState, body: str) -> None:
        """The one place a send changes state; compose and the status line follow it."""
        self._send_state = state
        self.prompt.text = body
        area = self.prompt.prompt_text_area
        area.disabled = bool(state.reason)
        # Disabling dropped the prompt's focus; give it back unless the reader moved on.
        if not area.disabled and self.is_attached and self.screen.focused is None:
            self.screen.set_focus(area)
        area.tooltip = state.reason or None
        self.status = state.reason

    async def submit_comms_message(self, root, kind, target, body, current, present):
        """CLI transcripts and wire pages use the same Core-send checks."""
        if not body.strip():
            return
        try:
            async with self.app.coordination_access.transcripts.bind(root) as comms:
                read_only = await self.app.preparation.run_thread(kind.read_only, comms, target)
        except (OSError, ValueError, RuntimeError) as error:
            self.delivery_refused(str(error), body)
            return
        if read_only:
            self.prompt.text = body
            self.prompt.prompt_text_area.disabled = True
            self.status = "Read-only saved view; open an exact channel to send"
            self.flash(self.status, style="error")
            return
        await self.deliver_user_message(root, kind.send_target(target), body, current, present)

    async def deliver_user_message(self, root, target, body, current, present):
        """One route check, write and failure path for CLI, DM and channel input."""
        from agent_comms.route_selection import root_is_current
        from agent_comms.delivery_failure import delivery_failure

        if self.send_block_reason:
            self.flash(self.send_block_reason, style="error")
            return
        self._enter_send_state(SendPending(), body)

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
        except Exception as error:
            delivery_failure(error).present(self, body)
            return
        sent = await self.commit_user_message(comms, target, body)
        if sent is None:
            return
        await present(sent)

    async def commit_user_message(self, comms, target, body):
        from agent_comms.route_selection import implicit_root, run_selected_write
        from agent_comms.delivery_failure import delivery_failure

        task = asyncio.create_task(asyncio.to_thread(
            run_selected_write, comms.root, comms.messaging.send_user_message,
            target, body, worktree=str(self.project_path), implicit=implicit_root()))
        try:
            sent = await asyncio.shield(task)
        except asyncio.CancelledError:
            self.delivery_blocked("Send cancelled while worker may still write; outcome UNKNOWN, inspect the bus, do not retry", body)
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
            return None
        except Exception as error:
            delivery_failure(error).present(self, body)
            return None
        self._enter_send_state(SentUndrawn(comms.root, sent), body)
        return sent

    def settle_user_message(self) -> None:
        """Enable compose only when the sent message is drawn."""
        if self._send_state.drawn_in(self):
            self._enter_send_state(NoSend(), "")

    def delivery_unknown(self, failure, body: str) -> None:
        self._enter_send_state(SendUnknown(failure), body)
        self.flash(self.send_block_reason, style="error")

    def delivery_blocked(self, description: str, body: str) -> None:
        self._enter_send_state(SendBlocked(description), body)
        self.flash(self.send_block_reason, style="error")

    def delivery_refused(self, description: str, body: str) -> None:
        self._enter_send_state(NoSend(), body)
        self.flash(f"Send failed: {description}", style="error")
