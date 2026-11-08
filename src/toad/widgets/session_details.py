"""One live status row expands the session's source and delivery details."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metaclass_registry.mro_dispatch import handles
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.registry.thread_presentation import (
    ThreadPresentationStatus,
    SessionDisconnected,
    WorkingThreadPresentationStatus,
    ThreadRetired,
)
from agent_comms.ui_model.status import ThreadStatusModel
from toad.core.projection import MroProjection
from toad.navigation_context import NavigationScope
from toad.tone_paint import TonePaint
from ui_theme.scheme import TurnBandColour
from textual.content import Content
from textual.reactive import var
from textual.widgets import Collapsible, Static

from toad.line_blocks import LineRole, MutedRole, NoticeRole, WorkingRole
from toad.native_style import (
    AutoHeight,
    Borderless,
    MutedText,
    NoMargin,
    NoPadding,
    ScrollsVertically,
    SidePadding,
)
from toad.widgets.input_delivery import DetailAction, InputDeliveryBar
from toad.widgets.native_history import NativeHistory
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.session_history_details import SessionHistoryDetails
from textual.events import Mount
from textual import on


if TYPE_CHECKING:
    from toad.transcript_publication import TranscriptPresentation
    from toad.widgets.conversation import Conversation


class InspectSession(DetailAction):
    """Opens the delivery details of the session its row names."""

    async def act(self) -> None:
        await self.query_ancestor(SessionDetails).inspect()


class SessionDetailsContents(
    ScrollsVertically,
    AutoHeight,
    SidePadding,
    Collapsible.Contents,
):
    """The disclosed details, bounded to a few scrolling rows."""

    DETAIL_ROWS = 8

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = self.DETAIL_ROWS


class SessionDetails(
    Borderless,
    MutedText,
    AutoHeight,
    NoPadding,
    NoMargin,
    TonePaint,
    Collapsible,
    ObservedThreadActivity,
    MroProjection[type[LineRole]],
):
    """The observed-thread capability and disclosure share one status view.

    Core owns status for an observed thread, native or CLI. A standalone ACP
    peer has only its local turn's status. Native turn permissions and
    settlement remain independent of this observed-thread presentation.
    """

    tone = TurnBandColour
    DEFAULT_ID = "session-details"
    overview_text: var[str] = var("")
    Contents = SessionDetailsContents

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        # The disclosure owns its one-line status title.
        title = self._title.styles
        title.width = "1fr"
        title.height = 1
        title.padding = (0, 1)
        title.text_wrap = "nowrap"
        title.text_overflow = "ellipsis"

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
            InspectSession("Inspect session", markup=False),
            self.notifications, history, delivery,
            title="", collapsed=True, id=self.DEFAULT_ID,
        )

    def status_source(self) -> ThreadStatusModel:
        return self.row

    async def inspect(self) -> None:
        """Which session this row's details belong to.

        A row inside the view it describes answers with that view. A row listing somebody
        else, as the channel sidebar's peer rows do (channel_activity.py:80), reaches the
        enclosing view instead of its own peer, which is the answer this walk has always
        given and is why the question belongs to the member rather than to the tree.
        """
        from toad.widgets.conversation import Conversation

        await self.query_ancestor(Conversation).inspect_session()

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
        return self.project_value(
            self.history.status.present_status(self.status_source().status)
        )

    @on(Mount)
    def on_mount(self) -> None:
        super().on_mount()
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
    def title_names(self) -> tuple[str, ...]:
        """The operational row is its own session; its status leads the title."""
        return ()

    def summary_title(self, row: ThreadStatusModel) -> str:
        """The collapsed row: its status, saved history and what delivery has to say.

        Delivery's parts come from delivery, which is the point: this line used to spell
        the notice count itself as f"{delivery.notices} notices" while the bar inside the
        expanded contents spelled the same count its own way, two paces below. One owner
        now, joined by whoever is joining.
        """
        delivery = self.delivery.delivery
        return " · ".join((
            *self.title_names, *row.summary, *self.history_details.summary,
            *delivery.parts(),
            *(("Delivery unavailable",) if delivery.error else ()),
        ))

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

    async def inspect(self) -> None:
        """This member holds its conversation, so it never asks the tree which one it is."""
        await self.conversation.inspect_session()

    def status_source(self) -> ThreadStatusModel:
        return self.conversation.operational_sources.status_row(self.conversation)


class ConversationSessionDetails(SessionDetails):
    """The same observed status row opens its thread from a conversation."""

    DEFAULT_ID = None

    def __init__(self, peer: ThreadIncarnation) -> None:
        self.peer = peer
        super().__init__(history=NativeHistory(), delivery=InputDeliveryBar())

    @property
    def label(self) -> str:
        return self.row.name

    @property
    def title_names(self) -> tuple[str, ...]:
        return (self.label,)

    async def _on_collapsible_title_toggle(self, event) -> None:
        event.prevent_default()
        event.stop()
        context = self.query_ancestor(NavigationScope).navigation_owner.navigation_context
        await self.app.thread_navigation.open_named(
            owner_mode=context.owner_mode, project_path=context.project_path,
            name=self.label)
