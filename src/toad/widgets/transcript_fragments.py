"""Textual-flavored transcript fragments: the canonical neutral family in
`toad.client.transcript_fragments` plus Textual's row acquisition and cursor-rest behavior.
Qt siblings of the same canonical family live in `toad.qt.history`; the consumer, slots,
builder and `FragmentPlan` live in `toad.client.transcript_fragments` so both frontends
share one event-stream reader, parameterized by the `FragmentClasses` each backend passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING

from toad.client.fragments import (
    CursorRest,
    Shown,
)
from toad.client.line_blocks import LineBlock
from toad.client.transcript_fragments import (
    BusMessageFragment as _BusMessageFragment,
    ContextTranscriptFragment as _ContextTranscriptFragment,
    FragmentClasses,
    FragmentLineConsumer,
    FragmentPlan,
    RenderBudget,
    SentMessageFragment as _SentMessageFragment,
    ToolTranscriptFragment as _ToolTranscriptFragment,
    TranscriptFragment as _TranscriptFragment,
)
from toad.menus import MenuCommand
from toad.render_backend import ReusableRenderTask
from toad.widgets.presentation_window import UNPLACED, Unplaced
from toad.widgets.transcript_lines import (
    AcquiredRows,
    BlockLines,
    Lines,
    LineTheme,
    NoRows,
    RowAcquisition,
    TranscriptLinesRenderTask,
    link_place,
)


if TYPE_CHECKING:
    from textual.widget import Widget

    from toad.block_navigation import FragmentBlockCursor
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import LineHistory


class TextualCursorRest(CursorRest):
    """No rest in a Textual history: it draws nowhere, selects nothing and shows nothing."""

    def drawn_in(self, history: LineHistory) -> CursorRest:
        """This rest while `history` draws it; no rest once it does not."""
        return self

    def selects(self, owner: Widget, history: LineHistory) -> bool:
        """Whether resting here selects `owner`: no rest selects nothing."""
        return False

    @property
    def block_menu(self) -> tuple[MenuCommand, ...]:
        return ()

    def placement_in(self, history: LineHistory) -> Unplaced:
        """Where the screen shows the rest: nowhere, until a fragment is rested on."""
        return UNPLACED

    def show_in(self, history: LineHistory) -> None:
        """Scroll a keyboard move's rest into view; no rest has nothing to show."""

    def show_head(self, cursor: FragmentBlockCursor, window: HistoryWindow) -> None:
        """Scroll a clicked rest's message head into view."""


NO_REST = TextualCursorRest()


@dataclass
class TranscriptFragment(_TranscriptFragment, TextualCursorRest):
    """A history fragment drawn by Textual: the canonical blocks derivation plus the row
    acquisition and cursor-rest behavior Textual's draw path needs. Qt's sibling uses the
    canonical class directly; this subclass exists only for what Textual adds."""

    _lines: RowAcquisition = field(default_factory=NoRows, init=False, repr=False, compare=False)

    _plain: RowAcquisition = field(default_factory=NoRows, init=False, repr=False, compare=False)

    def text_rows(self, lines: Lines) -> range:
        """The fragment's content occupies its drawn rows unless it owns a header."""
        return range(lines.height)

    def request_show(self, shown: Shown) -> bool:
        """Record intent and retire old acquisitions; the page retains its painted layout."""
        if not super().request_show(shown):
            return False
        # The rows drawn now stand in until the new state's rows arrive: a
        # status change must not redraw the message as plain rows (another
        # wrap, another height) and then as styled rows again.
        self._plain = self._lines.standing_in_for(self._plain)
        self.invalidate_lines()
        return True

    def drawn_in(self, history: LineHistory) -> CursorRest:
        return self if history.draws_fragment(self) else NO_REST

    def selects(self, owner: Widget, history: LineHistory) -> bool:
        return owner is history

    def placement_in(self, history: LineHistory) -> Unplaced:
        return history.fragment_shown(self)

    def show_in(self, history: LineHistory) -> None:
        history.show_fragment(self)

    def show_head(self, cursor: FragmentBlockCursor, window: HistoryWindow) -> None:
        cursor.block.run_worker(cursor.show_clicked_head(self, window), group="message-heading", exclusive=True)

    @cached_property
    def link_place(self) -> int:
        """What tells this fragment's drawn links apart from equal links in other fragments."""
        return link_place()

    def lines_for(self, width: int, theme: LineTheme) -> BlockLines:
        """Cached lookup is geometry-only; source changes use declared invalidation."""
        return self._lines.for_view(width, theme)

    def retains_lines(self, lines: BlockLines, theme: LineTheme) -> bool:
        """Whether measured rows still belong to this source and palette."""
        return self._lines.retains(lines, theme) or self._plain.retains(lines, theme)

    def invalidate_lines(self) -> None:
        self._lines = NoRows()

    def hold_lines(self, request: TranscriptLinesRenderTask, lines: BlockLines) -> bool:
        """Report whether these rows were retained for the fragment's source."""
        if request.blocks == self.line_blocks:
            self._lines = AcquiredRows(request.preparation, lines, request.context)
            return True
        return False

    def stand_in_lines(self, width: int, theme: LineTheme) -> BlockLines:
        """The styled rows drawn before a status change, rewrapped, until its new rows arrive."""
        return self._plain.for_view(width, theme)

    @property
    def retained_bytes(self) -> int:
        """This fragment's record and its acquired rows; the page owns events."""
        return super().retained_bytes + self._lines.preparation.retained_bytes + self._plain.preparation.retained_bytes


@dataclass(kw_only=True)
class ToolTranscriptFragment(_ToolTranscriptFragment, TranscriptFragment):
    """One tool call drawn by Textual: the canonical tool blocks derivation plus row acquisition."""


@dataclass(kw_only=True)
class BusMessageFragment(_BusMessageFragment, TranscriptFragment):
    """A bus message drawn by Textual."""


@dataclass(kw_only=True)
class SentMessageFragment(_SentMessageFragment, BusMessageFragment):
    """A sent bus message drawn by Textual."""


class ContextTranscriptFragment(_ContextTranscriptFragment, TranscriptFragment):
    """The coordination context an agent was given, drawn by Textual."""


TEXTUAL_FRAGMENT_CLASSES = FragmentClasses(
    transcript=TranscriptFragment,
    context=ContextTranscriptFragment,
    bus_message=BusMessageFragment,
    sent_message=SentMessageFragment,
    tool=ToolTranscriptFragment,
)


@dataclass(frozen=True)
class DraftBlocksRenderTask(ReusableRenderTask[tuple[LineBlock, ...]]):
    """A draft's source blocks: it grows with every chunk, so the worker parses it."""

    plan: FragmentPlan

    def result_size(self, result: tuple[LineBlock, ...]) -> int:
        return 64 + sum(block.retained_bytes for block in result)

    def execute(self) -> tuple[LineBlock, ...]:
        return tuple(block for fragment in self.plan.fragments() for block in fragment.line_blocks)
