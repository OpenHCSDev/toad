"""A channel or direct conversation drawn by the line history, with its read marks."""

from bisect import bisect_right
from dataclasses import dataclass

from agent_comms.messaging.messages import ConversationRole, Membership, NoticeRole
from textual._render_publication import SourcePublication
from textual.geometry import Offset, Region
from textual.reactive import var
from textual.strip import Strip
from textual.widgets import Static

from toad.client.pending import AwaitsFirstPage
from toad.block_navigation import ConversationBlock
from toad.client.fragments import EvidencedFragment, MembershipText, WireMessage
from toad.client.history import (
    ReadMarkedHistory,
    WirePageBuffer,
)
from toad.session_scope import SessionScope
from toad.client.prepared_pages import ClosedHistory
from toad.widgets.message_notifications import VisibleReadMarking
from toad.widgets.transcript_fragments import BusMessageFragment, TranscriptFragment
from toad.widgets.transcript_history import ConversationHistory, TranscriptPageView
from toad.widgets.transcript_lines import Lines
from toad.wire_conversation_view import WireConversationView


@dataclass(kw_only=True)
class WireFragment(EvidencedFragment, TranscriptFragment):
    """A wire message drawn by Textual, and the root of Textual's wire fragments: a message's
    role selects the member declared under it."""

    def text_rows(self, lines: Lines) -> range:
        """Read visibility uses the same block snapshots that draw this viewport."""
        prepared = lines.prepared_blocks
        trailing = len(self.trailing(self.shown))
        return range(
            sum(block.height for block in prepared[: len(self.leading)]),
            lines.height - sum(block.height for block in prepared[-trailing:] if trailing),
        )


@dataclass(kw_only=True)
class MembershipFragment(MembershipText, WireFragment, shows=(Membership,)):
    """Someone joined or left, drawn by Textual."""


@dataclass(kw_only=True)
class MessageFragment(WireMessage, BusMessageFragment, WireFragment, shows=(ConversationRole, NoticeRole)):
    """A sent message drawn by Textual."""


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

class WireHistory[ViewT: WireConversationView](AwaitsFirstPage, VisibleReadMarking, ReadMarkedHistory, ConversationHistory[ViewT]):
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

    @property
    def can_draw_on_screen(self) -> bool:
        return (super().can_draw_on_screen
                and self.view.query_ancestor(SessionScope).is_current)

    def withdraw_view(self) -> None:
        self.view.display = False

    def watch_reading(self, _reading: bool) -> None:
        self.view.sync_working()

    def first_page_drawn(self) -> None:
        if placeholder := self.view.query_one_optional(HistoryLoading):
            placeholder.remove()


