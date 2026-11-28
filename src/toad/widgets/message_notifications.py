"""Read-only notification feedback attached to its chat message."""

from __future__ import annotations

from collections.abc import Awaitable

from agent_comms.storage.maintenance_barrier import MaintenanceHeldError
from textual import on
from textual.app import ComposeResult
from textual.content import Content
from textual.css.native import NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.events import Click, Hide, Mount, Show, Unmount
from textual.widgets import Collapsible
from textual.widgets._collapsible import CollapsibleTitle
from textual.worker import Worker

from toad.app_node import ToadNode
from toad.client.history_notifications import HistoryNotifications
from toad.messages import QueueEvidenceOwner
from toad.native_style import (
    Borderless,
    EllipsisOverflow,
    FillWidth,
    MutedText,
    NoPadding,
    NoWrap,
    OneRow,
    TransparentBackground,
)
from toad.client.notification_status import (
    NotificationStatus,
    UncheckedNotifications,
)
from toad.project_path_owner import ProjectPathOwner
from toad.widgets.tool_content import ToolContent

from toad.client.history_reads import ReadMarking
from toad.no_worker import NoWorker


class NotificationTitle(
    NoPadding,
    FillWidth,
    OneRow,
    NoWrap,
    EllipsisOverflow,
    CollapsibleTitle,
):
    """One row whatever Core answers: the answer changes text and colour, never height."""

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        status = self.query_ancestor(MessageNotifications).status
        return (*super().native_declarations(),
                NativeDeclaration.of(Styles.color, Variable(status.role.colour.name)))


class MessageNotifications(
    Borderless,
    TransparentBackground,
    MutedText,
    NoPadding,
    Collapsible,
):

    class Contents(FillWidth, NoPadding, Collapsible.Contents):
        """Its look is its bases."""

    def __init__(self) -> None:
        self.status: NotificationStatus = UncheckedNotifications()
        self._details: ToolContent | None = None
        super().__init__(title=self.status.title, collapsed=True)
        title = self._title
        self._title = NotificationTitle(label=title.label, collapsed_symbol=title.collapsed_symbol,
                                        expanded_symbol=title.expanded_symbol, collapsed=title.collapsed)


    def compose(self) -> ComposeResult:
        yield self._title
        if self._details is not None:
            yield self.Contents(self._details)

    @property
    def details(self) -> ToolContent:
        """The details body, created only when it is first shown."""
        if self._details is None:
            self._details = ToolContent()
            if self.is_mounted:
                self.mount(self.Contents(self._details))
        self._details.update((self.status.disclosure,))
        return self._details

    @on(Click)
    def _stop_receipt_click(self, event: Click) -> None:
        """Clicking inside the read-receipt widget toggles or reads it; never bubble up to
        scroll its parent message back to the top."""
        event.stop()

    @on(Collapsible.Expanded)
    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            _ = self.details

    def show(self, status: NotificationStatus) -> None:
        if status == self.status:
            return
        self.status = status
        title = Content(status.title)
        if not title.is_same(Content.from_text(self.title)):
            self.title = title
        if not self.collapsed:
            _ = self.details
        self._title.update_node_styles()


class VisibleReadMarking(ReadMarking, ToadNode):
    """Textual runs a view's one painted read as a widget worker."""

    def __init__(self, *args, **kwargs):
        self._read_worker: Worker[None] | NoWorker = NoWorker()
        super().__init__(*args, **kwargs)

    def read_running(self) -> bool:
        return not self._read_worker.is_finished

    def start_read(self, work: Awaitable[None]) -> Worker[None]:
        self._read_worker = self.run_worker(work, group="painted-read")
        return self._read_worker

    def read_postponed(self, error: MaintenanceHeldError) -> None:
        self.log.debug("Read marking postponed during maintenance", error)


class VisibleHistoryNotifications(HistoryNotifications):
    """Textual subscribes while the view is mounted and shown, and runs each answer as a widget worker."""

    NOTIFICATION_GROUP = "message-notifications"

    @property
    def notification_root(self):
        root = ProjectPathOwner.containing(self).coordination_root
        if root is None:
            raise ValueError("Notification observation requires a bound thread root")
        return root

    def report_queue_evidence(self) -> None:
        self.query_ancestor(QueueEvidenceOwner).queue_evidence_changed()

    def run_notification_work(self, work: Awaitable[None]) -> None:
        self.run_worker(work, group=self.NOTIFICATION_GROUP, exclusive=True)

    def check_notifications_after_refresh(self) -> None:
        self.call_after_refresh(self.check_notifications)

    @on(Mount)
    def on_mount(self) -> None:
        self.call_after_refresh(self.check_notifications)

    @on(Unmount)
    def on_unmount(self) -> None:
        self.app.coordination_access.stop_notifications(self)

    @on(Hide)
    def on_hide(self) -> None:
        self.app.coordination_access.stop_notifications(self)

    @on(Show)
    def on_show(self) -> None:
        self.call_after_refresh(self.check_notifications)

