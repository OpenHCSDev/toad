"""A compact disclosure for session observations, provenance and delivery notices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.reactive import var
from textual.widgets import Collapsible

from toad.widgets.input_delivery import InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.session_history_details import SessionHistoryDetails
from toad.conversation_turn import ConversationTurn


if TYPE_CHECKING:
    from toad.transcript_publication import TranscriptPresentation


class SessionDetails(Collapsible):
    """Keep one summary row; native detail producers remain the state owners."""

    DETAIL_ROWS = 8
    """Tunable maximum expanded detail height, preserving room for the composer."""
    overview_text: var[str] = var("")

    DEFAULT_CSS = """
    SessionDetails, SessionDetails:ansi {
        height: auto; padding: 0; margin: 0; border: none;
        background: transparent; color: $text-muted;
    }
    SessionDetails > CollapsibleTitle {
        width: 1fr; height: 1; padding: 0 1; text-wrap: nowrap; text-overflow: ellipsis;
    }
    SessionDetails > Contents { height: auto; padding: 0 1; overflow-y: auto; }
    SessionDetails.-attention > CollapsibleTitle { color: $warning; }
    """

    def __init__(
        self, *,
        history: NativeHistory | None = None, delivery: InputDeliveryBar | None = None,
        transcript: TranscriptPresentation | None = None,
        turns: ConversationTurn | None = None,
    ) -> None:
        self.turns = turns
        self.activity = ObservedThreadActivity()
        self.history = history
        self.history_details = SessionHistoryDetails(transcript, history)
        self.delivery = delivery
        super().__init__(self.activity, *(item for item in (history, delivery) if item is not None),
                         title="Session details", collapsed=True, id="session-details")

    def on_mount(self) -> None:
        self.query_children(self.Contents).first().styles.max_height = self.DETAIL_ROWS
        self.watch(self.activity, "row", self._refresh_summary)
        if self.history is not None:
            self.watch(self.history, "status", self._refresh_summary)
        if self.delivery is not None:
            self.watch(self.delivery, "delivery", self._refresh_summary)
            self.watch(self.delivery, "error", self._refresh_summary)
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        row = self.activity.row
        shown = row is not None and row.shown
        parts = ["Session details"]
        attention = shown and row.attention
        if shown and not row.available:
            parts.extend(row.summary)
        elif self.turns is not None and self.turns.owner.busy:
            parts.append(self.turns.owner.activity)
        elif shown:
            parts.extend(row.summary)
        parts.extend(self.history_details.summary)
        attention |= self.history_details.attention
        if self.delivery is not None:
            delivery = self.delivery.delivery
            if delivery.current:
                parts.append(f"{delivery.current} {delivery.pending}")
                attention = True
            if delivery.notices:
                parts.append(f"{delivery.notices} notices")
            if self.delivery.error:
                parts.append("Delivery unavailable")
                attention = True
        if attention:
            parts.insert(1, "Needs attention")
        title = " · ".join(parts)
        if self.title != title:
            self.title = title
        self.set_class(attention, "-attention")
        self.overview_text = self.history_details.overview(self.activity)
        self.display = bool(shown
                            or self.history is not None and self.history.status is not None
                            or self.delivery is not None and self.delivery.display)

    def sync_turn(self) -> None:
        self._refresh_summary()
