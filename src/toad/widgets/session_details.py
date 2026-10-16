"""One live status row expands the session's provenance and delivery details."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_comms.mro_dispatch import handles
from agent_comms.thread_presentation import (
    AttentionThreadPresentationStatus, IdleThreadPresentationStatus,
    WorkingThreadPresentationStatus,
)
from textual.content import Content
from textual.reactive import var
from textual.widgets import Collapsible, Static

from toad.core.projection import MroProjection
from toad.line_blocks import LineRole, MutedRole, NoticeRole, WorkingRole
from toad.widgets.input_delivery import DetailAction, InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.session_history_details import SessionHistoryDetails
from toad.conversation_turn import ConversationTurn


if TYPE_CHECKING:
    from toad.transcript_publication import TranscriptPresentation


class SessionDetails(Collapsible, ObservedThreadActivity, MroProjection):
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
        self.notifications = Static("", markup=False)
        super().__init__(
            DetailAction("Inspect session", markup=False, id="session-inspect"),
            self.notifications, *(item for item in (history, delivery) if item is not None),
            title="", collapsed=True, id="session-details",
        )

    @handles(IdleThreadPresentationStatus)
    def idle_role(self, status) -> type[LineRole]:
        return MutedRole

    @handles(WorkingThreadPresentationStatus)
    def working_role(self, status) -> type[LineRole]:
        return WorkingRole

    @handles(AttentionThreadPresentationStatus)
    def attention_role(self, status) -> type[LineRole]:
        return NoticeRole

    @property
    def title_role(self) -> type[LineRole]:
        """Derive existing theme paint from the original status sources."""
        if self.history_details.attention:
            return NoticeRole
        if self.delivery is not None and (self.delivery.delivery.current or self.delivery.error):
            return NoticeRole
        row = self.row
        if row is not None and row.shown:
            return self.dispatch_sync(row.status)
        if self.turns is not None:
            return self.dispatch_sync(self.turns.owner.presentation_status)
        return MutedRole

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

    def notify_style_update(self) -> None:
        super().notify_style_update()
        if self.is_mounted:
            self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        row = self.row
        shown = row is not None and row.shown
        owner = self.turns.owner if self.turns is not None else None
        if shown:
            title = row.summary[0]
        else:
            title = owner.status if owner is not None else ""
        # The status is already the disclosure's title, not a second row inside.
        detail = "\n".join(row.lines[1:]) if shown else ""
        self.notifications.update(detail)
        self.notifications.display = bool(detail)
        label = Content.styled(title, self.app.colours.style(self.title_role))
        # Native Content compares text and spans; no last-title/status mirror.
        if not Content.from_text(self.title, markup=False).is_same(label):
            self.title = label
        self.overview_text = self.history_details.overview(row.lines if shown else ())
        self.display = bool(title)

    def sync_turn(self) -> None:
        self._refresh_summary()
