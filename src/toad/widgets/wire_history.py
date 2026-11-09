"""A channel or direct conversation drawn by the line history, with its read marks."""

from bisect import bisect_right
from dataclasses import dataclass

from textual.widgets import Static
from textual.geometry import Offset, Region
from textual.strip import Strip
from textual._render_publication import SourcePublication
from toad.widgets.transcript_fragments import FragmentKey

from toad.block_navigation import ConversationBlock

from toad.read_marked_history import ReadMarkedHistory
from toad.wire_conversation_view import WireConversationView

from textual.reactive import var

from agent_comms.coordination.errors import ReadAgain
from agent_comms.historical_views import UnobservedConversation
from agent_comms.messaging.message_page import MessagePage

from toad.session_scope import SessionScope
from toad.transcript_preparation import ClosedHistory, PreparedTranscriptPage
from toad.transcript_source_preparation import HistorySourceSnapshot
from toad.widgets.message_notifications import (
    NothingToRead,
    PaintedRead,
    VisibleReadMarking,
)
from toad.widgets.transcript_history import ConversationHistory, TranscriptPageView
from toad.wire_history import PreparedWirePage, WirePage, WirePageBuffer, WireSource, WireFragment




@dataclass(frozen=True)
class PaintedTranscriptRow:
    """One original body strip and its message, at the cells actually written."""

    fragment: WireFragment
    region: Region
    strip: Strip


@dataclass
class RenderedTranscriptRows(SourcePublication):
    history: WireHistory
    rows: dict[int, PaintedTranscriptRow]

    def admit(self, region: Region) -> None:
        if row := self.rows.get(region.y):
            if overlap := row.region.intersection(region):
                if row.strip.crop(overlap.x - row.region.x, overlap.right - row.region.x).text.strip():
                    self.history.retain_painted(row.fragment)


class ReadTranscriptPage(TranscriptPageView):
    """Bus-message body sources are captured by the paint that draws them."""

    def capture_render(self, origin: Offset, region: Region, strips: list[Strip]) -> RenderedTranscriptRows:
        """Capture message identities from these original strips before layout can change."""
        rows = {}
        for y, strip in zip(region.line_range, strips):
            local_y = y - origin.y
            slot = bisect_right(self._starts, local_y) - 1
            if slot < 0:
                continue
            fragment, first, lines = self._layout[slot]
            if local_y - first in fragment.text_rows(lines):
                rows[y] = PaintedTranscriptRow(fragment, Region(region.x, y, region.width, 1), strip)
        return RenderedTranscriptRows(self.history, rows)


class HistoryLoading(ConversationBlock, Static):
    """Channel history loading is an atomic conversation block."""

class WireHistory[ViewT: WireConversationView](VisibleReadMarking, ReadMarkedHistory, ConversationHistory[ViewT]):
    """The line history of a channel or direct conversation.

    Paging, preparation, trimming and the reader's position are the line
    history's. This adds what a wire conversation has: a source that grows
    under one viewer's reading of it, messages marked read when their text is
    seen, notification states and two styles.
    """

    page_view_type = ReadTranscriptPage
    page_source: WirePageBuffer | ClosedHistory
    # Reading the bound source's first page: the view's activity bar shows it.
    reading = var(False)

    def __init__(self, prepared: PreparedTranscriptPage, page_source: WirePageBuffer | ClosedHistory,
                 *, view: ViewT, notification_view, **kwargs) -> None:
        self._painted_reads: dict[FragmentKey, WireFragment] = {}
        super().__init__(prepared, page_source, view=view,
                         notification_view=notification_view, **kwargs)

    @classmethod
    def empty_page(cls):
        return PreparedWirePage.empty(WirePage.unread())

    # The source

    def initialize_source(self, source: WireSource) -> None:
        """Bind the conversation to read; the first refresh draws its newest page."""
        self._painted_reads.clear()
        self.page_source.close()
        self.page_source = WirePageBuffer(source, self.page_source.through, self.app.preparation,
                                          revision=UnobservedConversation())

    @property
    def undrawn(self) -> bool:
        """Nothing of the bound source has been drawn yet."""
        return all(view.prepared.page.after.requires_read() for view in self.pages)

    @property
    def source_identity(self):
        # Growth of the bus is not another source: reads ahead stay valid.
        return self.page_source.reload_key(), self.selected_categories

    @property
    def can_draw_on_screen(self) -> bool:
        return (super().can_draw_on_screen
                and self.view.query_ancestor(SessionScope).is_current)

    async def source_is_current(self, snapshot: HistorySourceSnapshot) -> bool:
        """Whether the route still selects this source's bus and nothing replaced the history."""
        source = self.page_source
        if not snapshot.current(self):
            return False
        return (await source.route_is_current()
                and source is self.page_source and snapshot.current(self))

    # Reading the source

    async def read_changes(self) -> bool:
        """Draw what changed in the source; False when the stores are as last drawn."""
        source = self.page_source
        self.reading = self.undrawn
        try:
            observed = await source.observe_changes(source.revision)
            if source is not self.page_source:
                return False
            return await observed.apply(self, source)
        finally:
            self.reading = False

    def watch_reading(self, _reading: bool) -> None:
        self.view.sync_working()

    # What is drawn

    def rows_published(self) -> None:
        super().rows_published()
        if not self.undrawn and (placeholder := self.view.query_one_optional(HistoryLoading)):
            placeholder.remove()

    async def toggle_style(self) -> None:
        """Draw every message in the other style, here and in pages read from now on."""
        await self.page_source.change_style(self)

    # Read marks

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        if self.can_draw_on_screen:
            self.mark_visible()

    def source_resumed(self) -> None:
        self.mark_visible()

    def retain_painted(self, fragment: WireFragment) -> None:
        """Keep actual painted evidence until its original page is acknowledged."""
        if fragment.evidence is not None and self._painted_reads.get(fragment.key) is not fragment:
            self._painted_reads[fragment.key] = fragment
            self.view.call_after_refresh(self.mark_visible)

    def retire_painted(self, fragments: tuple[WireFragment, ...], proof: MessagePage) -> None:
        """Release only these receipts, never a newer paint of the same message."""
        for fragment in fragments:
            if fragment.evidence is proof:
                fragment.evidence = None
                if self._painted_reads.get(fragment.key) is fragment:
                    del self._painted_reads[fragment.key]

    def read_fragments(self) -> tuple[WireFragment, ...]:
        if not self.is_attached or not self.can_draw_on_screen:
            return ()
        return tuple(self._painted_reads.values())

    def read_visible(self) -> PaintedRead:
        if not self.is_attached:
            return NothingToRead()
        if not any(fragment.evidence is not None for fragment in self.read_fragments()):
            return NothingToRead()
        return self.page_source.painted_read(self)

    async def _mark_read(self, snapshot: HistorySourceSnapshot) -> None:
        if not await self.source_is_current(snapshot):
            if snapshot.current(self):
                self.view.display = False
            elif self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
            return
        seen = tuple(fragment for fragment in self.read_fragments() if fragment.evidence is not None)
        if (selected := self.page_source.seen_page(self, seen)) is not None:
            await self._mark_page(*selected, snapshot)

    async def _mark_page(
        self, page: MessagePage, marked: tuple[WireFragment, ...], snapshot: HistorySourceSnapshot
    ) -> None:
        source = self.page_source
        proof = marked[0].evidence
        try:
            await source.mark_page(page)
            self.retire_painted(marked, proof)
        except ReadAgain:
            # Every queued fragment carrying that same refused proof must
            # release it before reloading can paint a replacement. Keep
            # unrelated proofs and any newer paint already queued meanwhile.
            refused = tuple(fragment for fragment in self._painted_reads.values()
                            if fragment.evidence is proof)
            self.retire_painted((*marked, *refused), proof)
            # The viewer, peer, channel scope or bus changed after the page
            # was read: draw the conversation as it is read now.
            if snapshot.current(self):
                await self.reload_notification_source()
        finally:
            if self.is_attached:
                self.view.call_after_refresh(self.mark_visible)

    async def reload_notification_source(self) -> None:
        """Forget what was observed, so the next refresh reads the page and its cut afresh."""
        self.page_source.revision = UnobservedConversation()
        await self.view._refresh()
