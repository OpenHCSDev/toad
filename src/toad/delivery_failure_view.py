"""The concrete compose controls used by shared delivery-failure declarations."""


class DeliveryFailureView:
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
        self._human_admission_blocked = True
        self._send_block_reason = f"Private human admission blocked: {description}"
        self._show_delivery_failure(self._send_block_reason, body, disabled=True)

    def delivery_refused(self, description: str, body: str) -> None:
        self._human_admission_blocked = False
        self._send_block_reason = ""
        self.prompt.text = body
        self.prompt.prompt_text_area.disabled = False
        self.flash(f"Send failed: {description}", style="error")
