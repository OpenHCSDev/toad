"""The concrete compose controls used by shared delivery-failure declarations."""


import asyncio


class DeliveryFailureView:
    """Own human-message write custody and its compose/failure controls."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._unknown_send = None
        self._send_block_reason = ""
        self._sent_undrawn = None

    @property
    def user_message_ready(self) -> bool:
        return self._unknown_send is None and not self._send_block_reason

    async def commit_user_message(self, comms, target, body):
        from agent_comms.route_selection import implicit_root, run_selected_write
        from agent_comms.delivery_failure import delivery_failure

        self._send_block_reason = "Send pending; do not retry"
        self.prompt.text = body
        self.prompt.prompt_text_area.disabled = True
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
        self._sent_undrawn = sent
        self._send_block_reason = f"Sent {comms.root}/{sent.seq}/{sent.message_id}; waiting to be drawn, do not retry"
        self.status = self._send_block_reason
        self.prompt.prompt_text_area.tooltip = self.status
        return sent

    def settle_user_message(self) -> None:
        """Enable compose only when the original committed message is drawn."""
        if self._sent_undrawn is None or not self.draws_user_message(self._sent_undrawn):
            return
        self._sent_undrawn = None
        self._send_block_reason = ""
        self.prompt.text = ""
        self.prompt.prompt_text_area.disabled = False
        self.prompt.prompt_text_area.tooltip = None
        self.status = ""

    def _show_delivery_failure(self, description: str, body: str, *, disabled: bool) -> None:
        self.prompt.text = body
        self.prompt.prompt_text_area.disabled = disabled
        self.status = description
        self.prompt.prompt_text_area.tooltip = description
        self.flash(description, style="error")

    def delivery_unknown(self, failure, body: str) -> None:
        self._unknown_send = (failure.wire_root_id, failure.wire_seq, failure.message_id)
        self._show_delivery_failure(f"Send UNKNOWN: {failure.description}; do not retry", body, disabled=True)

    def delivery_blocked(self, description: str, body: str) -> None:
        self._send_block_reason = f"Send blocked: {description}"
        self._show_delivery_failure(self._send_block_reason, body, disabled=True)

    def delivery_refused(self, description: str, body: str) -> None:
        self._send_block_reason = ""
        self.prompt.text = body
        self.prompt.prompt_text_area.disabled = False
        self.flash(f"Send failed: {description}", style="error")
