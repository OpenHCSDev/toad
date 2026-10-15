"""One live status row expands the session's provenance and delivery details."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.reactive import var
from textual.widgets import Collapsible, Static

from toad.widgets.input_delivery import DetailAction, InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.session_history_details import SessionHistoryDetails
from toad.conversation_turn import ConversationTurn


if TYPE_CHECKING:
    from toad.transcript_publication import TranscriptPresentation


class SessionDetails(Collapsible, ObservedThreadActivity):
    """The observed-thread capability and disclosure share one status view.

    Core owns status for an observed thread, native or CLI. A standalone ACP
    peer has only its local turn's status. Native turn permissions and
    settlement remain independent of this observed-thread presentation.
    """

    DETAIL_ROWS = 8
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
    SessionDetails.-working > CollapsibleTitle { color: $accent; }
    SessionDetails.-attention > CollapsibleTitle { color: $warning; }
    SessionDetails .session-notifications { height: auto; }
    """

    def __init__(
        self, *,
        history: NativeHistory | None = None, delivery: InputDeliveryBar | None = None,
        transcript: TranscriptPresentation | None = None,
        turns: ConversationTurn | None = None,
    ) -> None:
        self.turns = turns
        self.history = history
        self.history_details = SessionHistoryDetails(transcript, history)
        self.delivery = delivery
        self.notifications = Static("", markup=False, classes="session-notifications")
        super().__init__(
            DetailAction("Inspect session", markup=False, id="session-inspect"),
            self.notifications, *(item for item in (history, delivery) if item is not None),
            title="", collapsed=True, id="session-details",
        )

    def on_mount(self) -> None:
        super().on_mount()
        self.query_children(self.Contents).first().styles.max_height = self.DETAIL_ROWS
        if self.history is not None:
            self.watch(self.history, "status", self._refresh_summary)
        if self.delivery is not None:
            self.watch(self.delivery, "delivery", self._refresh_summary)
            self.watch(self.delivery, "error", self._refresh_summary)
        self._refresh_summary()

    def activity_changed(self) -> None:
        self._refresh_summary()
        super().activity_changed()

    def _refresh_summary(self, *_args) -> None:
        row = self.row
        shown = row is not None and row.shown
        owner = self.turns.owner if self.turns is not None else None
        attention = shown and row.attention
        if shown:
            title = row.summary[0]
        else:
            title = owner.status if owner is not None else ""
        if self.title != title:
            self.title = title
        # The status is already the disclosure's title, not a second row inside.
        detail = "\n".join(row.lines[1:]) if shown else ""
        self.notifications.update(detail)
        self.notifications.display = bool(detail)
        attention |= self.history_details.attention
        if self.delivery is not None:
            delivery = self.delivery.delivery
            attention |= bool(delivery.current or self.delivery.error)
        self.set_class(attention, "-attention")
        self.set_class(row.working if shown else owner is not None and owner.busy, "-working")
        self.overview_text = self.history_details.overview(self)
        self.display = bool(title)

    def sync_turn(self) -> None:
        self._refresh_summary()
