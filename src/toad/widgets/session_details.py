"""A compact disclosure for session observations, provenance and delivery notices."""

from collections.abc import Awaitable, Callable

from agent_comms.thread_presentation import ThreadPresentation
from textual import on
from textual.reactive import var
from textual.widgets import Collapsible

from toad.widgets.input_delivery import InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity


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
        height: 1; padding: 0 1; text-wrap: nowrap; text-overflow: ellipsis;
    }
    SessionDetails > Contents { height: auto; padding: 0 1; overflow-y: auto; }
    SessionDetails.-attention > CollapsibleTitle { color: $warning; }
    """

    def __init__(
        self, read: Callable[[], Awaitable[ThreadPresentation | None]], *,
        history: NativeHistory | None = None, delivery: InputDeliveryBar | None = None,
    ) -> None:
        self.activity = ObservedThreadActivity(read)
        self.history = history
        self.delivery = delivery
        super().__init__(self.activity, *(item for item in (history, delivery) if item is not None),
                         title="Session details", collapsed=True, id="session-details")

    def on_mount(self) -> None:
        self.query_children(self.Contents).first().styles.max_height = self.DETAIL_ROWS
        self.watch(self.activity, "display", self._refresh_summary)
        if self.history is not None:
            self.watch(self.history, "status", self._refresh_summary)
        if self.delivery is not None:
            self.watch(self.delivery, "delivery", self._refresh_summary)
            self.watch(self.delivery, "error", self._refresh_summary)
        self._refresh_summary()

    @on(ObservedThreadActivity.Changed)
    def observed_activity_changed(self, event: ObservedThreadActivity.Changed) -> None:
        # The same event still reaches Conversation's activity/Ready policy.
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        activity = self.activity
        presentation = activity.presentation
        parts = ["Session details"]
        attention = activity.unavailable
        if activity.unavailable:
            parts.append("Status unavailable")
        elif presentation is not None:
            parts.append(presentation.summary.partition("\n")[0] or "Ready")
            if presentation.notifications:
                parts.append(f"{len(presentation.notifications)} recent")
        if self.history is not None and self.history.status == "unavailable":
            parts.append("History unavailable")
            attention = True
        if self.delivery is not None:
            delivery = self.delivery.delivery
            current = len(delivery["inputs"])
            notices = delivery["historicalCount"] or delivery["dismissedHistoricalCount"]
            if current:
                parts.append(f"{current} awaiting start" if delivery.get("currentScope") == "owner_queue"
                             else f"{current} unconfirmed")
                attention = True
            if notices:
                parts.append(f"{notices} notices")
            if self.delivery.error:
                parts.append("Delivery unavailable")
                attention = True
        if attention:
            parts.insert(1, "Needs attention")
        title = " · ".join(parts)
        if self.title != title:
            self.title = title
        self.set_class(attention, "-attention")
        self.overview_text = "\n\n".join(
            str(item.render()) for item in (self.activity, self.history)
            if item is not None and item.display
        )
        self.display = bool(presentation is not None or activity.unavailable
                            or self.history is not None and self.history.status is not None
                            or self.delivery is not None and self.delivery.display)
