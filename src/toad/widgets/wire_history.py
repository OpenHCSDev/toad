"""A channel or direct conversation drawn by the line history, with its read marks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_comms.messages import Message
from agent_comms.coordination_errors import DMPaintedBoundChanged, DMScopeChanged, HistoricalSourceChanged

from toad.screens.session_view import SessionView
from toad.transcript_preparation import ClosedHistory, PreparedTranscriptPage
from toad.transcript_source_preparation import HistorySourceSnapshot
from toad.transcript_state import LatestViewportRequest
from toad.widgets.history_anchor import LatestPosition
from toad.widgets.message_filter import OtherCategory, all_categories
from toad.widgets.message_notifications import VisibleReadMarking
from toad.widgets.transcript_history import LineHistory
from toad.wire_history import PreparedWirePage, WirePage, WirePageBuffer, WireSource

if TYPE_CHECKING:
    from agent_comms.historical_views import ConversationRevision

class WireHistory(VisibleReadMarking, LineHistory):
    """The line history of a channel or direct conversation.

    Paging, preparation, trimming and the reader's position are the line
    history's. This adds what a wire conversation has: a source that grows
    under one viewer's reading of it, messages marked read when their text is
    seen, notification states and two styles.
    """

    page_source: WirePageBuffer | ClosedHistory

    def __init__(self, prepared: PreparedTranscriptPage, page_source: WirePageBuffer | ClosedHistory,
                 *, view, notification_view) -> None:
        self.view = view
        super().__init__(prepared, page_source, notification_view=notification_view)
        # Core's source observation is independent of paint readiness.
        self.revision: ConversationRevision | None = None

    @classmethod
    def empty(cls, *, view, notification_view):
        prepared = PreparedWirePage.empty(WirePage.unread())
        return cls(prepared, ClosedHistory(prepared.page.after, view.app.preparation),
                   view=view, notification_view=notification_view)

    # The source

    def open(self, source: WireSource) -> None:
        """Bind the conversation to read; the first refresh draws its newest page."""
        self.page_source.close()
        self.page_source = WirePageBuffer(source, self.page_source.through, self.app.preparation)

    @property
    def undrawn(self) -> bool:
        """Nothing of the bound source has been drawn yet."""
        return all(view.prepared.page.undrawn for view in self.pages)

    @property
    def source_identity(self):
        # Growth of the bus is not another source: reads ahead stay valid.
        return self.page_source.reload_key(), self.selected_categories

    @property
    def can_draw_on_screen(self) -> bool:
        return (super().can_draw_on_screen
                and self.view.query_ancestor(SessionView).is_current)

    async def source_is_current(self, snapshot: HistorySourceSnapshot) -> bool:
        """Whether the route still selects this source's bus and nothing replaced the history."""
        source = self.page_source
        if not snapshot.current(self):
            return False
        return (await source.route_is_current()
                and source is self.page_source and snapshot.current(self))

    @property
    def selected_categories(self):
        # Every wire message is in one category: a filter shows all or none.
        return (all_categories() if OtherCategory in self.view.visible_categories
                else frozenset())

    # Reading the source

    async def read_changes(self) -> bool:
        """Draw what changed in the source; False when the stores are as last drawn."""
        source = self.page_source
        observed = await source.observe_changes(self.revision)
        if source is not self.page_source:
            return False
        if observed is not None:
            # Record Core's observation before asynchronous drawing. A pending
            # viewport must not turn the same scope into another replacement.
            self.revision = observed.revision
            if observed.replaced:
                await self.show_newest(observed.through, PreparedWirePage.empty(WirePage.unread()))
                return not self.undrawn
            if not self.undrawn:
                return await self.extend(observed.through)
            self.extend_source(observed.through)
        elif not self.undrawn:
            # A recorded observation may still have an unfinished page read.
            return (self.pages[-1].prepared.page.after != source.through
                    and await self.extend(source.through))
        # The existing prepared reader owns this pending page. Retry drawing it,
        # not clearing its source and starting the same read again.
        await self._jump_latest(LatestViewportRequest(LatestPosition.hold(self.window)))
        return not self.undrawn

    # What is drawn

    async def accept_extension(self, edge, prepared) -> bool:
        if self.page_source.accepts_page(edge.prepared.page, prepared.page):
            return True
        prepared.configure(batch_size=len(prepared.fragments))
        await self.show_newest(self.page_source.through, PreparedWirePage.empty(WirePage.unread()),
                               arrivals=self._source_state.arriving(prepared, self.drawn_tail_followed))
        return False

    def draws(self, message: Message) -> bool:
        """Whether the drawn rows include this message, checking the newest first."""
        return any(fragment.message.view_key == message.view_key
                   for fragment in reversed(self.fragments_in_range))

    async def toggle_style(self) -> None:
        """Draw every message in the other style, here and in pages read from now on."""
        await self.page_source.change_style(self)

    def notification_read(self, references):
        return self.page_source.notification_read(references)

    def subscribe_notifications(self, references) -> None:
        self.page_source.observe_notifications(self, references)

    # Read marks

    def read_visible(self):
        if not self.is_attached:
            return None
        if not any(fragment.evidence is not None for fragment in self.read_fragments()):
            return None
        return self.page_source.painted_read(self)

    async def _mark_read(self, snapshot: HistorySourceSnapshot) -> None:
        if not await self.source_is_current(snapshot):
            if snapshot.current(self):
                self.view.display = False
            elif self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
            return
        seen = tuple(fragment for fragment in self.read_fragments() if fragment.evidence is not None)
        historical = next((fragment.evidence for fragment in seen
                           if fragment.evidence.historical_display is not None), None)
        if historical is not None:
            await self._mark_historical(
                historical, tuple(fragment for fragment in seen if fragment.evidence is historical),
                snapshot)
        elif (selected := self.page_source.seen_page(self, seen)) is not None:
            await self._mark_page(*selected, snapshot)

    async def _mark_historical(self, page, marked, snapshot: HistorySourceSnapshot) -> None:
        displayed = page.select(fragment.message.seq for fragment in marked).historical_display
        try:
            await self.page_source.mark_historical(displayed)
        except (HistoricalSourceChanged, DMScopeChanged):
            # The attached history changed; this page's evidence marks nothing any more.
            marked = tuple(fragment for fragment in self.fragments if fragment.evidence is page)
        if snapshot.current(self):
            for fragment in marked:
                fragment.evidence = None

    async def _mark_page(self, page, marked, snapshot: HistorySourceSnapshot) -> None:
        source = self.page_source
        try:
            await source.mark_page(page)
            if snapshot.current(self):
                for fragment in marked:
                    fragment.evidence = None
        except (DMScopeChanged, DMPaintedBoundChanged):
            # The viewer, peer, channel scope or bus changed after the page
            # was read: draw the conversation as it is read now.
            if snapshot.current(self):
                await self._clear(PreparedWirePage.empty(WirePage.unread()))
                await self.view._refresh()
        finally:
            if self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
