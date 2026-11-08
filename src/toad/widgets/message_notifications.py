"""Read-only notification feedback attached to its chat message."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass, replace

from textual.app import ComposeResult
from textual.content import Content
from textual.css.native import NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.worker import Worker
from textual.widgets import Collapsible
from textual.widgets._collapsible import CollapsibleTitle

from agent_comms.storage.maintenance_barrier import MaintenanceHeldError
from agent_comms.notification_reads import LiveNotificationRead
from agent_comms.ui_model.observation import ReadNotifications
from agent_comms.read_basis import DisplayIdentity, NoDisplaySelection
from agent_comms.message_reference import MessageReference
from toad.app_node import ToadNode
from toad.messages import QueueEvidenceOwner
from toad.project_path_owner import ProjectPathOwner
from toad.widgets.tool_content import ToolContent
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

from toad.notification_status import (
    CheckedNotifications, MessageQueueEntry, NotificationStatus, UnavailableNotifications, UncheckedNotifications,
)
from textual.events import Mount
from textual import on

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


class PaintedRead(ABC):
    """What a view can start after its current rows have been painted."""

    @abstractmethod
    def start(self, marker: VisibleReadMarking) -> Worker[None] | None:
        pass


class NothingToRead(PaintedRead):
    def start(self, marker: VisibleReadMarking) -> None:
        pass


@dataclass(frozen=True)
class ReadWork(PaintedRead):
    work: Awaitable[None]

    async def run(self, marker: VisibleReadMarking) -> None:
        try:
            await self.work
        except MaintenanceHeldError as error:
            # The refused evidence stays unread; a later paint supplies fresh work.
            marker.log.debug("Read marking postponed during maintenance", error)

    def start(self, marker: VisibleReadMarking) -> Worker[None]:
        marker._read_worker = marker.run_worker(self.run(marker), group="painted-read")
        return marker._read_worker


class VisibleReadMarking(ToadNode):
    """One painted-read operation at a time, for pagers and native/CLI sessions."""

    def __init__(self, *args, **kwargs):
        self._read_worker: Worker[None] | None = None
        super().__init__(*args, **kwargs)

    def mark_visible(self) -> None:
        if self._read_worker is not None and not self._read_worker.is_finished:
            return
        self.read_visible().start(self)


class HistoryNotifications:
    """Visible history rows subscribe to Core; paging never decides when outcomes changed."""

    NOTIFICATION_GROUP = "message-notifications"
    notification_operation = LiveNotificationRead

    # Core feedback for every visible bus message, native or wire.

    def check_notifications(self) -> None:
        fragments = self.notification_targets() if self.can_draw_on_screen else ()
        references = tuple(dict.fromkeys(
            reference for fragment in fragments for reference in fragment.notification_references))
        if self.subscribe_notifications(references):
            # Only a changed set of visible messages changes the queue evidence.
            self.query_ancestor(QueueEvidenceOwner).queue_evidence_changed()

    def notification_read(self, references: Iterable[MessageReference]) -> ReadNotifications:
        root = ProjectPathOwner.containing(self).coordination_root
        if root is None:
            raise ValueError("Notification observation requires a bound thread root")
        references = tuple(references)
        wanted = frozenset(references)
        display = next((target.notification_identity_for(wanted)
                        for target in self.notification_targets()
                        if wanted.intersection(target.notification_references)), NoDisplaySelection())
        return ReadNotifications(root, self.notification_operation(references), display=display)

    def subscribe_notifications(self, references) -> bool:
        """Whether the read this view shows changed."""
        access = self.app.coordination_access
        if references:
            return access.show_notifications(self, self.notification_read(references))
        return access.stop_notifications(self)

    def notifications_observed(self, results) -> None:
        if not self.can_draw_on_screen:
            self.app.coordination_access.stop_notifications(self)
            return
        self.run_worker(self._show_notifications(results), group=self.NOTIFICATION_GROUP, exclusive=True)

    async def _show_notifications(self, results):
        for target in self.notification_targets():
            await target.show_notifications(results)
        self.query_ancestor(QueueEvidenceOwner).queue_evidence_changed()

    def notifications_failed(self, failure: Exception) -> None:
        if self.can_draw_on_screen:
            self.run_worker(self._show_notification_error(UnavailableNotifications(str(failure))),
                            group=self.NOTIFICATION_GROUP, exclusive=True)

    async def _show_notification_error(self, status):
        for target in self.notification_targets():
            await target.show_notification_status(status)
        self.query_ancestor(QueueEvidenceOwner).queue_evidence_changed()

    def notifications_reload(self) -> None:
        """Core answered this read's display cut is gone: its page is read again, and the
        rows it draws carry the fresh cut the next read asks with."""
        if self.can_draw_on_screen:
            self.run_worker(self._reload_notification_sources(),
                            group=self.NOTIFICATION_GROUP, exclusive=True)

    async def _reload_notification_sources(self):
        for target in self.notification_targets():
            await target.reload_notification_source()

    @on(Mount)
    def on_mount(self) -> None:
        self.call_after_refresh(self.check_notifications)

    def on_unmount(self) -> None:
        self.app.coordination_access.stop_notifications(self)

    def on_hide(self) -> None:
        self.app.coordination_access.stop_notifications(self)

    def on_show(self) -> None:
        self.call_after_refresh(self.check_notifications)


class SourceNotifications:
    notification_view: HistoryNotifications

    def queue_entries(self) -> Iterable[MessageQueueEntry]:
        for fragment in self.visible_fragments():
            yield from fragment.queue_entries()

    def notification_identity_for(self, references: frozenset[MessageReference]) -> DisplayIdentity | NoDisplaySelection:
        """Use the visible BUS fragments' construction-time display identity."""
        return next((fragment.notification_identity
                     for fragment in reversed(tuple(self.visible_fragments()))
                     if references.intersection(fragment.notification_references)), NoDisplaySelection())

    def rows_published(self) -> None:
        super().rows_published()
        self.notification_view.call_after_refresh(self.notification_view.check_notifications)

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        self.notification_view.check_notifications()

    @property
    def notification_references(self):
        return tuple(dict.fromkeys(reference for fragment in self.visible_fragments()
                                   for reference in fragment.notification_references))

    async def show_notifications(self, results):
        await self._show([(fragment, replace(fragment.shown, status=status))
            for fragment in self.visible_fragments()
            for status in CheckedNotifications.for_references(fragment.notification_references, results)])

    async def show_notification_status(self, status):
        await self._show([(fragment, replace(fragment.shown, status=fragment.shown.status.failed(status)))
                         for fragment in self.visible_fragments() if fragment.notification_references])

    def retire_source(self, *, parked: bool = False):
        retired = super().retire_source(parked=parked)
        self.notification_view.check_notifications()
        return retired

    async def close_source_reader(self) -> None:
        await super().close_source_reader()
        # A closing reader leaves its subscriptions; no live view shows queue evidence for it.
        self.notification_view.subscribe_notifications(())
