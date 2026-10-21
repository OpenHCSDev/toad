"""One live status row expands the session's source and delivery details."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_comms.mro_dispatch import handles
from agent_comms.thread_presentation import (
    ThreadPresentationStatus, SessionDisconnected,
    WorkingThreadPresentationStatus, ThreadRetired,
)
from agent_comms.ui_model.status import ThreadStatusModel
from toad.core.projection import MroProjection
from toad.frame_presentation import TonePaint
from ui_theme.scheme import TurnBandColour
from textual.content import Content
from textual.reactive import var
from textual.widgets import Collapsible, Static

from toad.line_blocks import LineRole, MutedRole, NoticeRole, WorkingRole
from toad.widgets.input_delivery import DetailAction, InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.session_history_details import SessionHistoryDetails


if TYPE_CHECKING:
    from toad.transcript_publication import TranscriptPresentation
    from toad.widgets.conversation import Conversation


class SessionDetails(TonePaint, Collapsible, ObservedThreadActivity, MroProjection):
    """The observed-thread capability and disclosure share one status view.

    Core owns status for an observed thread, native or CLI. A standalone ACP
    peer has only its local turn's status. Native turn permissions and
    settlement remain independent of this observed-thread presentation.
    """

    tone = TurnBandColour
    DETAIL_ROWS = 8
    DEFAULT_ID = "session-details"
    overview_text: var[str] = var("")

    DEFAULT_CSS = """
    SessionDetails, SessionDetails:ansi {
        height: auto; padding: 0; margin: 0; border: none;
        color: $text-muted;
    }
    SessionDetails > CollapsibleTitle {
        width: 1fr; height: 1; padding: 0 1; text-wrap: nowrap; text-overflow: ellipsis;
    }
    SessionDetails > Contents { height: auto; padding: 0 1; overflow-y: auto; }
    """

    def __init__(
        self, *,
        history: NativeHistory, delivery: InputDeliveryBar,
        transcript: TranscriptPresentation | None = None,
    ) -> None:
        self.history = history
        self.history_details = SessionHistoryDetails(transcript, history)
        self.delivery = delivery
        self.notifications = Static("", markup=False)
        super().__init__(
            DetailAction("Inspect session", markup=False, id="session-inspect"),
            self.notifications, history, delivery,
            title="", collapsed=True, id=self.DEFAULT_ID,
        )

    def status_source(self) -> ThreadStatusModel:
        return self.row

    @handles(ThreadPresentationStatus)
    def idle_role(self, status) -> type[LineRole]:
        return NoticeRole if status.details else MutedRole

    @handles(WorkingThreadPresentationStatus)
    def working_role(self, status) -> type[LineRole]:
        return WorkingRole

    @handles(ThreadRetired)
    def retired_role(self, status) -> type[LineRole]:
        return NoticeRole

    @handles(SessionDisconnected)
    def disconnected_role(self, status) -> type[LineRole]:
        return NoticeRole

    @property
    def title_role(self) -> type[LineRole]:
        return self.dispatch_sync(
            self.history.status.present_status(self.status_source().status)
        )

    def on_mount(self) -> None:
        super().on_mount()
        self.query_children(self.Contents).first().styles.max_height = self.DETAIL_ROWS
        self.watch(self.history, "status", self._refresh_summary)
        self.watch(self.delivery, "delivery", self._refresh_summary)
        self._refresh_summary()

    def activity_changed(self) -> None:
        self._refresh_summary()
        super().activity_changed()

    def notify_style_update(self) -> None:
        super().notify_style_update()
        if self.is_mounted:
            self._refresh_summary()

    @property
    def label(self) -> str:
        return "Session details"

    def summary_title(self, row: ThreadStatusModel) -> str:
        """The collapsed row: what this is, its status, saved history and delivery notices."""
        parts = [self.label, *row.summary, *self.history_details.summary]
        delivery = self.delivery.delivery
        if delivery.notices:
            parts.append(f"{delivery.notices} notices")
        if delivery.error:
            parts.append("Delivery unavailable")
        return " · ".join(parts)

    def _refresh_summary(self, *_args) -> None:
        row = self.status_source()
        title = self.summary_title(row)
        # The status is already the disclosure's title, not a second row inside.
        detail = "\n".join(row.lines[1:])
        self.notifications.update(detail)
        self.notifications.display = bool(detail)
        label = Content.styled(title, self.app.colours.style(self.title_role))
        # Native Content compares text and spans; no last-title/status mirror.
        if not Content.from_text(self.title, markup=False).is_same(label):
            self.title = label
        self.overview_text = self.history_details.overview(row.lines)
        self.display = bool(row.summary[0])

    def sync_turn(self) -> None:
        self._refresh_summary()


class OperationalSessionDetails(SessionDetails):
    """The agent's status source is available before its disclosure is mounted."""

    def __init__(self, conversation: Conversation, **kwargs) -> None:
        self.conversation = conversation
        super().__init__(**kwargs)

    def status_source(self) -> ThreadStatusModel:
        return self.conversation.operational_sources.status_row(self.conversation)


class ConversationSessionDetails(SessionDetails):
    """The same observed status row opens its thread from a conversation."""

    DEFAULT_ID = None

    def __init__(self, peer) -> None:
        self.peer = peer
        super().__init__(history=NativeHistory(), delivery=InputDeliveryBar())

    @property
    def label(self) -> str:
        return self.row.name

    async def _on_collapsible_title_toggle(self, event) -> None:
        event.prevent_default()
        event.stop()
        context = self.app.selected_session.navigation_context
        references = (
            self.app.coordination_access.observation.observed()
            .sidebar.observation.require_snapshot().references
        )
        await self.app.thread_navigation.open(
            owner_mode=context.owner_mode, project_path=context.project_path,
            target=references.thread(self.peer).name)
