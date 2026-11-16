"""Core's notification answers for the bus messages a history draws.

Every frontend's history subscribes for the messages it shows and redraws their status rows
from what Core answers; the frontend says where its rows are and how its work runs.
"""

from abc import abstractmethod
from collections.abc import Awaitable, Iterable
from dataclasses import replace

from agent_comms.messaging.message_reference import MessageReference
from agent_comms.messaging.notification_reads import LiveNotificationRead
from agent_comms.messaging.read_basis import DisplayIdentity, NoDisplaySelection
from agent_comms.ui_model.observation import ReadNotifications

from toad.client.application import ClientApplication
from toad.client.fragments import HistoryFragment, Shown
from toad.client.notification_status import CheckedNotifications, MessageQueueEntry, UnavailableNotifications
from toad.client.subscribers import NotificationSubscriber


class HistoryNotifications(NotificationSubscriber):
    """Visible history rows subscribe to Core; paging never decides when outcomes changed."""

    notification_operation = LiveNotificationRead
    app: ClientApplication

    # What the frontend supplies

    @abstractmethod
    def notification_targets(self) -> tuple[SourceNotifications, ...]:
        """The histories drawn in this view right now."""

    @property
    @abstractmethod
    def can_draw_on_screen(self) -> bool: ...

    @property
    @abstractmethod
    def notification_root(self) -> str:
        """The bus root the view's messages are read from."""

    @abstractmethod
    def report_queue_evidence(self) -> None:
        """The visible messages' notifications changed: whatever shows queue evidence reads them again."""

    @abstractmethod
    def run_notification_work(self, work: Awaitable[None]) -> None:
        """Run `work`, replacing the notification work still running."""

    @abstractmethod
    def check_notifications_after_refresh(self) -> None:
        """Check notifications once the rows just published are drawn."""

    # Core feedback for every visible bus message, native or wire.

    def check_notifications(self) -> None:
        fragments = self.notification_targets() if self.can_draw_on_screen else ()
        references = tuple(dict.fromkeys(
            reference for fragment in fragments for reference in fragment.notification_references))
        if self.subscribe_notifications(references):
            # Only a changed set of visible messages changes the queue evidence.
            self.report_queue_evidence()

    def notification_read(self, references: Iterable[MessageReference]) -> ReadNotifications:
        references = tuple(references)
        wanted = frozenset(references)
        display = next((target.notification_identity_for(wanted)
                        for target in self.notification_targets()
                        if wanted.intersection(target.notification_references)), NoDisplaySelection())
        return ReadNotifications(self.notification_root, self.notification_operation(references),
                                 display=display)

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
        self.run_notification_work(self._show_notifications(results))

    async def _show_notifications(self, results):
        for target in self.notification_targets():
            await target.show_notifications(results)
        self.report_queue_evidence()

    def notifications_failed(self, failure: Exception) -> None:
        if self.can_draw_on_screen:
            self.run_notification_work(self._show_notification_error(UnavailableNotifications(str(failure))))

    async def _show_notification_error(self, status):
        for target in self.notification_targets():
            await target.show_notification_status(status)
        self.report_queue_evidence()

    def notifications_reload(self) -> None:
        """Core answered this read's display cut is gone: its page is read again, and the
        rows it draws carry the fresh cut the next read asks with."""
        if self.can_draw_on_screen:
            self.run_notification_work(self._reload_notification_sources())

    async def _reload_notification_sources(self):
        for target in self.notification_targets():
            await target.reload_notification_source()


class SourceNotifications:
    notification_view: HistoryNotifications

    @abstractmethod
    def _show(self, changes: list[tuple[HistoryFragment, Shown]]) -> Awaitable[None]:
        """Draw each fragment as it is now shown."""

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
        self.notification_view.check_notifications_after_refresh()

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
