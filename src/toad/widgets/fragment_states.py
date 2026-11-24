"""Where one fragment lives in the mounted history, and the row-change a fresh render asks of
the page that drew it.

The states and changes stay toolkit-neutral; the page, window and line widgets they reference
come from each backend. `FragmentSpan` still inherits `BlockSpan` from
`toad.widgets.transcript_lines` — moving that one is a follow-up AGENT-6 lift, not this PR.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import accumulate
from typing import TYPE_CHECKING, ClassVar

from agent_comms.nominal.fold import Absorbs, Accumulates, Fold

from toad.client.fragments import FragmentKey
from toad.client.reader_position import (
    FragmentLocation,
    FragmentPosition,
    ReaderPosition,
    UnloadedFragment,
)
from toad.message_rows import RecordedMessageClock
from toad.widgets.presentation_window import UNPLACED, Unplaced
from toad.widgets.transcript_lines import BlockSpan


if TYPE_CHECKING:
    from textual.widget import Widget
    from toad.block_navigation import FragmentBlockCursor
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_fragments import TranscriptFragment
    from toad.widgets.transcript_history import (
        LaidOutRow,
        LineHistory,
        TranscriptPageView,
    )
    from toad.widgets.transcript_lines import BlockLines


@dataclass(frozen=True)
class FragmentSpan(BlockSpan, FragmentLocation):
    """A block span placed in its page, carrying the message it belongs to."""

    fragment: TranscriptFragment = field(kw_only=True)
    page: TranscriptPageView = field(kw_only=True)

    @classmethod
    def in_page(cls, page: TranscriptPageView, fragment: TranscriptFragment,
                first: int, span: BlockSpan) -> FragmentSpan:
        return cls(index=span.index, first=first + span.first, height=span.height,
                   drawn=span.drawn, fragment=fragment, page=page)

    def location(self) -> FragmentSpan:
        return self

    def tooltip(self) -> str | None:
        return RecordedMessageClock(self.fragment.timestamp).display()[1]

    def selected_by(self, cursor: FragmentBlockCursor) -> bool:
        cursor.fragment = self.fragment
        return True

    def bodies(self) -> tuple[Widget, ...]:
        return (self.page,)

    def for_layout(self, window: HistoryWindow, position: ReaderPosition) -> ReaderPosition:
        return position

    def find_in(self, pages: Iterator[TranscriptPageView], position: FragmentPosition) -> FragmentLocation:
        return self

    def laid_out(self, window: HistoryWindow) -> bool:
        return self.page.rows_measured and any(window.placements(self.bodies()))

    def destination(self, window: HistoryWindow, fraction: float) -> float:
        # A hidden child lands on the next drawn sibling, otherwise the previous.
        return window.row_of(self.page) + self.first + (fraction * self.height if self.drawn else 0)


class RowChange(Fold):
    """What new lines ask of the page that draws them: repaint rows in their measured box, or
    measure the page again. A page folds the changes of every fragment that changed."""

    @abstractmethod
    def apply(self, page: TranscriptPageView) -> None: ...


@dataclass(frozen=True)
class RepaintRows(Accumulates, RowChange):
    rows: tuple[tuple[LaidOutRow, BlockLines], ...] = ()

    def including(self, repaint: RepaintRows) -> RepaintRows:
        return RepaintRows(self.rows + repaint.rows)

    def apply(self, page: TranscriptPageView) -> None:
        for row, lines in self.rows:
            page.repaint_row(row.slot, lines)


class MeasureAgain(Absorbs, RowChange):
    """One fragment whose rows cannot keep their box sends the whole page to layout."""

    def apply(self, page: TranscriptPageView) -> None:
        page.range_changed()


class UndrawnFragment:
    """No loaded page draws this fragment: it has no rows and the screen shows none."""

    draws: ClassVar[bool] = False
    rows = range(0)

    @property
    def placement(self) -> Unplaced:
        """Where the screen shows the page drawing the fragment."""
        return UNPLACED

    def shown(self) -> Unplaced:
        return self.placement.shown_rows(self.rows)

    def head_on_screen(self, window: HistoryWindow) -> bool:
        """Whether the fragment's first row is drawn at or below the viewport's top."""
        return self.placement.shows_from(self.rows.start, window.scrollable_content_region.y)

    def head_hidden(self, window: HistoryWindow, height: int) -> bool:
        """Whether a message of this height starting here needs its head placed."""
        return self.placement.head_hidden(self.rows.start, window, height)

    def show(self, history: LineHistory) -> None:
        """Scroll just far enough that the fragment's rows are on screen; an undrawn one has none."""


UNDRAWN = UndrawnFragment()


@dataclass(frozen=True)
class DrawnFragment(UndrawnFragment):
    """The page that draws a fragment and its rows there."""

    draws = True
    page: TranscriptPageView
    rows: range

    @property
    def placement(self) -> Unplaced:
        return self.page.placement

    def show(self, history: LineHistory) -> None:
        """Layout places only the pages near the screen. Pages follow one another
        without a gap, so the first placed page gives the window rows of every other."""
        pages = history.pages
        starts = dict(zip(pages, accumulate((p.line_count for p in pages), initial=0)))
        for placed_page, placed in history.window.placements(pages):
            shift = starts[self.page] + placed - starts[placed_page]
            history.window.show_rows(range(self.rows.start + shift, self.rows.stop + shift))
            return


class LaidOut(ABC):
    """A fragment's rows in its page's measured layout, or their absence."""

    def measured_again(self) -> RowChange:
        return MeasureAgain()

    @abstractmethod
    def replaced_by(self, lines: BlockLines) -> RowChange: ...

    @abstractmethod
    def placement(self, page: TranscriptPageView) -> UndrawnFragment: ...

    @abstractmethod
    def placed(self, candidate: TranscriptFragment, key: FragmentKey, block: int) -> FragmentLocation: ...


class NotLaidOut(LaidOut):
    """A fragment the last layout drew no rows for."""

    def replaced_by(self, lines: BlockLines) -> RowChange:
        return self.measured_again()

    def placement(self, page: TranscriptPageView) -> UndrawnFragment:
        return UNDRAWN

    def placed(self, candidate: TranscriptFragment, key: FragmentKey, block: int) -> FragmentLocation:
        return UnloadedFragment()


NOT_LAID_OUT = NotLaidOut()
