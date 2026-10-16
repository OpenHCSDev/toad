"""Read-only notification feedback attached to its chat message."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Collapsible

from toad.notification_status import (
    CheckedNotifications, NotificationStatus, UnavailableNotifications, UncheckedNotifications,
)
from toad.line_blocks import SpanColumns
from toad.widgets.tool_content import ToolContent

if TYPE_CHECKING:
    from toad.widgets.transcript_fragments import TranscriptFragment


class NotificationDetails(ToolContent):
    """Use the existing line-block view's width, preparation and link lifecycle."""

    def show(self, disclosure: SpanColumns) -> None:
        self.update((disclosure,))


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
        self._details: NotificationDetails | None = None
        super().__init__(title=self.status.title, collapsed=True)

    def compose(self) -> ComposeResult:
        yield self._title
        if self._details is not None:
            yield self.Contents(self._details)

    @property
    def details(self) -> NotificationDetails:
        """The details body, created only when it is first shown."""
        if self._details is None:
            self._details = NotificationDetails()
            if self.is_mounted:
                self.mount(self.Contents(self._details))
        self._details.show(self.status.disclosure)
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

    def show_error(self, error: Exception) -> None:
        self.show(UnavailableNotifications(str(error)))


class VisibleReadMarking:
    """One painted-read operation at a time, for pagers and native/CLI sessions."""

    def __init__(self, *args, **kwargs):
        self._read_worker = None
        super().__init__(*args, **kwargs)

    def mark_visible(self) -> None:
        if self._read_worker is not None and not self._read_worker.is_finished:
            return
        if (work := self.read_visible()) is not None:
            self._read_worker = self.run_worker(work, group="painted-read")

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        if self.can_draw_on_screen:
            self.mark_visible()

    def source_resumed(self) -> None:
        self.mark_visible()


class HistoryNotifications:
    """Visible history rows subscribe to Core; paging never decides when outcomes changed."""

    NOTIFICATION_GROUP = "message-notifications"

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        self.check_notifications()

    # Core feedback for every visible bus message, native or wire.

    def check_notifications(self) -> None:
        access = self.app.coordination_access
        fragments = self._notified_fragments() if self.can_draw_on_screen else ()
        references = tuple(dict.fromkeys(
            reference for fragment in fragments for reference in fragment.notification_references))
        access.show_notifications(self, self.notification_read(references) if references else None)

    def _notified_fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for fragment in self.visible_fragments()
                     if fragment.checks_notifications)

    def notifications_observed(self, results) -> None:
        if not self.can_draw_on_screen:
            self.app.coordination_access.show_notifications(self, None)
            return
        self.run_worker(self._show([
            (fragment, replace(fragment.shown, status=CheckedNotifications.for_references(
                fragment.notification_references, results)))
            for fragment in self._notified_fragments()
            if all((reference.seq, reference.message_id) in results
                   for reference in fragment.notification_references)
        ]), group=self.NOTIFICATION_GROUP, exclusive=True)

    def notifications_failed(self, failure: Exception) -> None:
        if self.can_draw_on_screen:
            self.run_worker(self._show([
                (fragment, replace(fragment.shown, status=UnavailableNotifications(str(failure))))
                for fragment in self._notified_fragments()
            ]), group=self.NOTIFICATION_GROUP, exclusive=True)

    def retire_source(self, *, parked: bool = False):
        self.app.coordination_access.show_notifications(self, None)
        return super().retire_source(parked=parked)

    async def close_source_reader(self) -> None:
        self.app.coordination_access.show_notifications(self, None)
        await super().close_source_reader()

    def on_hide(self) -> None:
        self.app.coordination_access.show_notifications(self, None)

    def on_show(self) -> None:
        self.call_after_refresh(self.check_notifications)
