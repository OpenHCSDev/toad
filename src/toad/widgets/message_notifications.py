"""Read-only notification feedback attached to its chat message."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Collapsible

from agent_comms.notification_reads import LiveNotificationRead
from agent_comms.ui_model.observation import ReadNotifications
from agent_comms.read_basis import DisplayIdentity, NoDisplaySelection
from agent_comms.message_reference import MessageReference
from toad.submission_queue import QueueEvidenceChanged

from toad.notification_status import (
    CheckedNotifications, NotificationStatus, UnavailableNotifications, UncheckedNotifications,
)
if TYPE_CHECKING:
    from toad.widgets.tool_content import ToolContent
    from toad.widgets.transcript_fragments import TranscriptFragment


class MessageNotifications(Collapsible):
    DEFAULT_CSS = """
    MessageNotifications {
        height: auto; padding: 0; margin: 0; border: none;
        background: transparent; color: $text-muted;
        CollapsibleTitle { padding: 0; min-height: 1; }
        Contents { padding: 0; }
    }
    MessageNotifications.-working > CollapsibleTitle { color: $accent; }
    MessageNotifications.-unavailable > CollapsibleTitle { color: $warning; }
    """

    def __init__(self) -> None:
        self.status: NotificationStatus = UncheckedNotifications()
        self._details: ToolContent | None = None
        super().__init__(title=self.status.title, collapsed=True)

    def compose(self) -> ComposeResult:
        yield self._title
        if self._details is not None:
            yield self.Contents(self._details)

    @property
    def details(self) -> ToolContent:
        """The details body, created only when it is first shown."""
        if self._details is None:
            from toad.widgets.tool_content import ToolContent

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
        self.set_class(status.working, "-working")
        self.set_class(status.unavailable, "-unavailable")


class PaintedRead(ABC):
    """What a view can start after its current rows have been painted."""

    @abstractmethod
    def start(self, marker: VisibleReadMarking) -> None:
        pass


class NothingToRead(PaintedRead):
    def start(self, marker: VisibleReadMarking) -> None:
        pass


@dataclass(frozen=True)
class ReadWork(PaintedRead):
    work: Awaitable[None]

    def start(self, marker: VisibleReadMarking) -> None:
        marker._read_worker = marker.run_worker(self.work, group="painted-read")


class VisibleReadMarking:
    """One painted-read operation at a time, for pagers and native/CLI sessions."""

    def __init__(self, *args, **kwargs):
        self._read_worker = None
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
        self.subscribe_notifications(references)
        self.post_message(QueueEvidenceChanged())

    def notification_read(self, references: Iterable[MessageReference]) -> ReadNotifications:
        from toad.project_path_owner import ProjectPathOwner

        root = ProjectPathOwner.containing(self).coordination_root
        if root is None:
            raise ValueError("Notification observation requires a bound thread root")
        references = tuple(references)
        wanted = frozenset(references)
        display = next((target.notification_identity_for(wanted)
                        for target in self.notification_targets()
                        if wanted.intersection(target.notification_references)), NoDisplaySelection())
        return ReadNotifications(root, self.notification_operation(references), display=display)

    def subscribe_notifications(self, references) -> None:
        access = self.app.coordination_access
        if references:
            access.show_notifications(self, self.notification_read(references))
        else:
            access.stop_notifications(self)

    def notifications_observed(self, results) -> None:
        if not self.can_draw_on_screen:
            self.app.coordination_access.stop_notifications(self)
            return
        self.run_worker(self._show_notifications(results), group=self.NOTIFICATION_GROUP, exclusive=True)

    async def _show_notifications(self, results):
        for target in self.notification_targets():
            await target.show_notifications(results)
        self.post_message(QueueEvidenceChanged())

    def notifications_failed(self, failure: Exception) -> None:
        if self.can_draw_on_screen:
            self.run_worker(self._show_notification_error(UnavailableNotifications(str(failure))),
                            group=self.NOTIFICATION_GROUP, exclusive=True)

    async def _show_notification_error(self, status):
        for target in self.notification_targets():
            await target.show_notification_status(status)
        self.post_message(QueueEvidenceChanged())

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

    def notification_identity_for(self, references: frozenset[MessageReference]) -> DisplayIdentity | NoDisplaySelection:
        """Use retained prepared Core pages, even after the pending paint was retired."""
        return next((page.prepared.notification_identity for page in reversed(self.pages)
                     if any(references.intersection(fragment.notification_references)
                            for fragment in page.prepared.fragments_in_range)), NoDisplaySelection())

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
        await self._show([(fragment, replace(fragment.shown, status=status))
                         for fragment in self.visible_fragments() if fragment.notification_references])

    def retire_source(self, *, parked: bool = False):
        retired = super().retire_source(parked=parked)
        self.notification_view.check_notifications()
        return retired

    async def close_source_reader(self) -> None:
        await super().close_source_reader()
        self.notification_view.check_notifications()
