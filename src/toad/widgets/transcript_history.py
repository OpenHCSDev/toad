"""Bounded, cursor-paged saved history; all transcript interpretation is model-owned."""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from contextlib import AsyncExitStack, asynccontextmanager
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from functools import cached_property, partial
from itertools import accumulate, chain, islice
from typing import TYPE_CHECKING, ClassVar, Final
from weakref import ref

from agent_comms.acp_extension import InputStartedUpdate
from metaclass_registry.mro_dispatch import handles
from agent_comms.sent_message import PublishedSentMessage
from agent_comms.transcript_events import TranscriptEvent
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.ui_model.message_category import (
    MessageCategory,
    all_categories,
)
from rich.style import Style as RichStyle
from textual import on
from toad.widget_actions import Activates
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual._paint_state import PaintState
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.geometry import Region, Size
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker
from ui_theme.effects import NEW_TEXT

from toad.block_navigation import ConversationEntry, FragmentBlockCursor
from toad.core.source_events import TranscriptCoverage
from toad.message_rows import RecordedMessageClock
from toad.native_style import (
    AutoHeight,
    MutedText,
    OneRow,
    PointerCursor,
    SecondaryText,
)
from toad.no_worker import NoWorker
from toad.session_scope import SessionScope
from toad.transcript_filter import FilterState
from toad.transcript_preparation import (
    ClosedHistory,
    PageFragmentRange,
    PreparedPageSource,
    PreparedTranscriptPage,
    ProjectedTranscriptSource,
    RangeCategoryProjection,
    ReplaceablePageSource,
    SavedHistory,
    UnreadTranscriptPage,
)
from toad.transcript_source_preparation import (
    TranscriptSourcePreparation,
    _DrawingStopped,
)
from toad.transcript_state import (
    LatestViewportRequest,
    LiveTranscript,
    ParkedSourceTranscript,
    ReplacementViewportRequest,
    TranscriptState,
)
from toad.widgets.committed_presentation import (
    RETAINED_SOURCE_CLAIM,
    CommitClaim,
    SnapshotPresentation,
)
from toad.widgets.history_anchor import (
    FragmentLocation,
    FragmentNotLoaded,
    FragmentPosition,
    HistoryWindow,
    LatestPosition,
    ReaderPosition,
    UnloadedFragment,
)
from toad.widgets.linked_rows import (
    HorizontalRows,
    OpensLinks,
    ReferenceRendering,
    selection_painted,
)
from toad.widgets.message_notifications import HistoryNotifications, SourceNotifications
from toad.widgets.presentation_window import (
    NEWER_END,
    OLDER_END,
    UNPLACED,
    PageEnd,
    PointerRows,
    PresentationBudget,
    Unplaced,
    arranged,
)
from toad.widgets.selection import HoverSelection
from toad.widgets.transcript_fragments import (
    FragmentDetails,
    FragmentKey,
    Shown,
    TranscriptFragment,
)
from agent_comms.nominal.fold import Absorbs, Accumulates, Fold
from toad.widgets.transcript_lines import (
    BlockLines,
    BlockSpan,
    LinePreparation,
    Lines,
    LineTheme,
    RowAcquisition,
    TranscriptLinesBatchRenderTask,
    TranscriptLinesRenderTask,
)

if TYPE_CHECKING:
    from agent_comms.messages import Message as BusMessage

    from toad.widgets.conversation import Contents, Conversation



class HistoryEdge(MutedText, OneRow, PointerCursor, Activates, Static, can_focus=True):

    class Requested(Message):
        pass


    def activate(self) -> None:
        self.post_message(self.Requested())

class JumpToLatest(SecondaryText, HoverSelection, HistoryEdge):
    highlighted_text_style = RichStyle(bold=True)

    class Requested(Message):
        pass

async def settled[Value](value: Value) -> Value:
    """An awaitable already holding its value, for a branch that has nothing to wait on."""
    return value


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


@dataclass(frozen=True, eq=False)
class LaidOutRow(LaidOut):
    """One fragment's measured rows; the page's layout holds them, this reads them."""

    page: TranscriptPageView
    slot: int

    @property
    def first(self) -> int:
        return self.page._layout[self.slot][1]

    @property
    def lines(self) -> BlockLines:
        return self.page._layout[self.slot][2]

    def replaced_by(self, lines: BlockLines) -> RowChange:
        """Lines filling the same box repaint in place, so no other message shows through it;
        lines of another height need layout."""
        return RepaintRows(((self, lines),)) if lines.height == self.lines.height else MeasureAgain()

    def placement(self, page: TranscriptPageView) -> UndrawnFragment:
        return DrawnFragment(page, range(self.first, self.first + self.lines.height))

    def placed(self, candidate: TranscriptFragment, key: FragmentKey, block: int) -> FragmentLocation:
        same = candidate.key == key
        wanted = block if same else 0
        # No drawn child at or after the wanted one: the candidate places nothing.
        return self.lines.block_span(lambda span: span.drawn and span.index >= wanted).placed_by(
            lambda span: replace(FragmentSpan.in_page(self.page, candidate, self.first, span),
                                 drawn=same and span.index == block),
            UnloadedFragment)


class TranscriptPageView(
    AutoHeight,
    PointerRows[FragmentLocation],
    ReferenceRendering,
    HorizontalRows,
    Widget,
):
    """One transcript page, drawn as its loaded fragments' prepared lines.

    Fragments never become widgets. Styled rows come from the render worker
    processes. A page styles a range's unstyled fragments before measuring it; after a status
    change a fragment draws its previous styled rows until its new ones arrive.
    The history marks arriving fragments; only their rows rise out of the background.
    """

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.overflow_x = "auto"
        self.styles.overflow_y = "hidden"

    def __init__(self, prepared: PreparedTranscriptPage, *,
                 batch_size: int = PresentationBudget.batch_items) -> None:
        # Arriving fragments by source key: an id() outlives an evicted fragment and names another.
        self.arrivals: set[FragmentKey] = set()
        self.prepared: Final[PreparedTranscriptPage] = prepared
        self.visible_categories = all_categories()
        self.prepared.configure(batch_size=batch_size)
        # Styling a range's never-styled fragments before the page measures them.
        self._style_worker: Worker[None] | NoWorker = NoWorker()
        # The rows this page draws are the rows layout last measured: each
        # drawn fragment, its first row and its lines at the measured width.
        # A changed range draws nothing new until layout has given it a box.
        self._width = 0
        self._layout: list[tuple[TranscriptFragment, int, BlockLines]] = []
        self._starts: list[int] = []
        self._fragment_slots: dict[FragmentKey, LaidOutRow] = {}
        self._height = 0
        self._measured = False
        super().__init__()

    @property
    def history(self) -> LineHistory:
        return self.query_ancestor(LineHistory)

    @property
    def line_sets(self) -> tuple[Lines, ...]:
        return tuple(lines for _, _, lines in self._layout)

    @handles(FragmentDetails)
    def toggle_details(self, link: FragmentDetails) -> None:
        """The painted action already names its occurrence in this page."""
        for fragment in self.prepared.fragments_in_range:
            if fragment.key == link.key:
                self.history.show_details(self, fragment, fragment.shown.toggled())
                return

    @property
    def line_width(self) -> int:
        """The width this page last laid out at; reading it never forces layout."""
        return self._width

    @property
    def line_count(self) -> int:
        return self._height

    @property
    def rows_measured(self) -> bool:
        """Whether the rows this page reports are those of the messages it has now."""
        return self._measured

    def on_mount(self) -> None:
        self.history.window.page_views.add(self)

    def invalidate_lines(self) -> None:
        for fragment in self.prepared.fragments:
            fragment.invalidate_lines()
        self.range_changed()

    def lines_replaced(self, fragments: Iterable[TranscriptFragment]) -> None:
        """These fragments of this page now hold new lines; each one's rows decide whether they
        repaint in their measured box or the page measures again."""
        theme = self.app.colours.line_theme
        change: RowChange = RepaintRows()
        for fragment in fragments:
            row = self._fragment_slots.get(fragment.key, NOT_LAID_OUT)
            change = fragment.row_change(row, self._width, theme).joined(change)
        change.apply(self)

    def repaint_row(self, slot: int, lines: BlockLines) -> None:
        """New lines of the measured height take that row's place."""
        fragment, first, _measured = self._layout[slot]
        self._layout[slot] = (fragment, first, lines)
        self.refresh(Region(0, first, self._width, lines.height))

    def range_changed(self) -> None:
        """The prepared range, its lines or the filter changed; the next layout measures the new rows.

        The rows drawn stay the measured ones until then. Drawing the new
        rows in the box of the old ones would show the reader other messages
        for a frame, before layout puts them back on their row.
        """
        self._measured = False
        self.refresh(layout=True)

    def _lines(self, fragment: TranscriptFragment, width: int) -> BlockLines:
        """The fragment's styled rows, or the styled rows it drew before a status change."""
        theme = self.app.colours.line_theme
        return fragment.lines_for(width, theme).styled_or(partial(fragment.stand_in_lines, width, theme))

    def _style_before_measuring(self, fragments: tuple[TranscriptFragment, ...]) -> None:
        """Style fragments that have no rows yet, then measure: their height is stated once,
        by their styled rows, so the reader is never placed against a stand-in height."""
        if self._style_worker.is_finished:
            # A widget worker: unmount cancels it and a failure is an app error.
            self._style_worker = self.run_worker(self._style_then_measure(fragments), group="style-before-measuring")

    async def _style_then_measure(self, fragments: tuple[TranscriptFragment, ...]) -> None:
        history = self.history
        await history.prepare_fragments(fragments, lambda: self.is_attached,
                                        selected=self.visible_categories, target=history)
        if self.is_attached:
            self.range_changed()

    def _measure(self, width: int) -> None:
        shown = tuple(fragment for fragment in self.prepared.fragments_in_range
                      if fragment.shown_in(self.visible_categories)) if width > 0 else ()
        drawn = tuple((fragment, self._lines(fragment, width)) for fragment in shown)
        unstyled = tuple(waiting for fragment, lines in drawn for waiting in lines.unstyled(fragment))
        if unstyled:
            # The rows drawn stay the measured ones until these have styled rows.
            self._style_before_measuring(unstyled)
            return
        if self.is_mounted:
            self.history.window.keep_reader()
        if width != self._width:
            # Native box/arrangement caches can retain A/B/A width variants.
            # Their numeric heights cannot restore this page's row snapshot;
            # retire them when replacing the geometry they were measured from.
            self._invalidate_layout()
        self._width, self._measured = width, True
        previous = {fragment.key: lines for fragment, _first, lines in self._layout}
        layout, starts, y = [], [], 0
        repaint = []
        if width > 0:
            # Geometry belongs to this layout's width, including rows outside
            # the viewport, and every fragment measured here has styled rows.
            for fragment, lines in drawn:
                if fragment.key in previous and lines is not previous[fragment.key]:
                    repaint.append((y, lines.height))
                layout.append((fragment, y, lines))
                starts.append(y)
                y += lines.height
        self._layout, self._starts, self._height = layout, starts, y
        for first, height in repaint:
            self.refresh(Region(0, first, width, height))
        self._fragment_slots = {fragment.key: LaidOutRow(self, index)
                                for index, (fragment, _first, _lines) in enumerate(layout)}
        if self.is_mounted:
            self.history.request_preparation()

    def prepare_viewport(self, window) -> None:
        """Prepare only the measured rows the window currently exposes."""
        theme = self.app.colours.line_theme
        visible = tuple(self.visible_rows(window))
        if any(lines.width != self._width or not fragment.retains_lines(lines, theme)
               for fragment, _rows, lines in visible):
            self.range_changed()
            return

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container, viewport, width: int) -> int:
        # The loaded fragments wrapped at this width: the container's height
        # is never read, so an arrangement measured at height 0 is reused.
        if width != self._width or not self._measured:
            self._measure(width)
        return self._height

    def render_line(self, y: int, paint: PaintState) -> Strip:
        # Layout supplies the width through get_content_height; reading size
        # here would look this widget up in the compositor for every row.
        width = self._width
        slot = bisect_right(self._starts, y) - 1
        if slot < 0:
            return selection_painted(self, self.blank_row(width, paint), y)
        fragment, first, lines = self._layout[slot]
        row = y - first
        if row >= lines.height:
            return selection_painted(self, self.blank_row(width, paint), y)
        # Prepared rows span exactly this width (Lines.strips_at).
        strip = lines.strips_at(fragment.link_place)[row]
        if fragment.key in self.arrivals:
            history = self.history
            strip = history.effect_phase(NEW_TEXT).paint(history, NEW_TEXT, strip)
        return selection_painted(self, self.on_background(strip, paint, y), y)

    def hold_fragment_top(self, window: HistoryWindow, key: FragmentKey) -> None:
        """Keep this page's activated source occurrence at the top while its details change."""
        placed = self.fragment_row(key, 0).location()
        if placed.drawn:
            window.reader_position = FragmentPosition(key, 0, placed.height, block=0)

    def fragment_row(self, key: FragmentKey, block: int) -> FragmentLocation:
        """A source child's first measured row, height and whether the page draws it.

        A hidden fragment lands on the next drawn fragment, otherwise the
        previous one. UnloadedFragment means this page has no drawn destination
        for the source position; source preparation fills an empty range.
        """
        loaded = self.prepared.fragments_in_range
        for at, target in enumerate(loaded):
            if target.key != key:
                continue
            return next((placed for candidate in chain(loaded[at:], reversed(loaded[:at]))
                         if (placed := self._fragment_slots.get(candidate.key, NOT_LAID_OUT)
                             .placed(candidate, key, block)).located), UnloadedFragment())
        return UnloadedFragment()

    @property
    def drawn_fragments(self) -> tuple[TranscriptFragment, ...]:
        """The fragments this page draws rows for, oldest first."""
        return tuple(fragment for fragment, _first, _lines in self._layout)

    def drawn_height(self, fragment: TranscriptFragment) -> int:
        """The rows this page draws for a fragment it draws."""
        return self._fragment_slots[fragment.key].lines.height

    def fragment_placement(self, fragment: TranscriptFragment) -> UndrawnFragment:
        """Where this page draws a fragment, or that it draws none of it."""
        return self._fragment_slots.get(fragment.key, NOT_LAID_OUT).placement(self)

    @property
    def placement(self) -> Unplaced:
        """Where the screen shows this page, including the part scrolled out of view."""
        return arranged(self)

    def shown_row(self, row: int) -> FragmentLocation:
        return self.fragment_at(row) if 0 <= row < self._height else UnloadedFragment()

    def unshown(self) -> FragmentLocation:
        return UnloadedFragment()

    def fragment_under_mouse(self) -> FragmentLocation:
        return self.placement.under(self, self.app.mouse_position.y)

    @property
    def tooltip(self) -> str | None:
        """The full time of the message under the pointer."""
        return self.fragment_under_mouse().tooltip()

    def fragment_at(self, row: int) -> FragmentLocation:
        """The measured child drawn here, with its containing message, or that none is."""
        slot = bisect_right(self._starts, row) - 1
        if slot < 0:
            return UnloadedFragment()
        fragment, first, lines = self._layout[slot]
        return lines.block_span(lambda span: span.contains(row - first)).placed_by(
            partial(FragmentSpan.in_page, self, fragment, first), UnloadedFragment)

    def visible_rows(self, window: HistoryWindow, margin: int = 0) -> Iterator[tuple[TranscriptFragment, range, Lines]]:
        """Each loaded fragment in the window's viewport, widened by `margin` rows each way,
        with its rows that are in that band."""
        # A page the viewport layout did not place is off screen; computing
        # its offset would rebuild the compositor's whole map.
        for _, offset in window.placements((self,)):
            top = int(window.scroll_y - offset) - margin
            bottom = top + window.outer_size.height + 2 * margin
            slot = max(0, bisect_right(self._starts, top) - 1)
            for index in range(slot, len(self._layout)):
                fragment, first, lines = self._layout[index]
                if first >= bottom:
                    break
                if first + lines.height > top:
                    yield fragment, range(max(0, top - first), min(lines.height, bottom - first)), lines

    def visible_fragments(self, window: HistoryWindow) -> tuple[TranscriptFragment, ...]:
        """The fragments this page draws inside the window's viewport."""
        return tuple(fragment for fragment, _rows, _lines in self.visible_rows(window))

    @classmethod
    @asynccontextmanager
    async def acquire(
        cls, owner: LineHistory, prepared: PreparedTranscriptPage, *,
        end: PageEnd, pages: deque[TranscriptPageView], current: Callable[[], bool],
    ) -> AsyncIterator[TranscriptPageView]:
        """Acquire the original prepared range, without selecting it a second time."""
        view = cls(prepared)
        view.visible_categories = owner.selected_categories
        view.display = False
        # Styled before it is drawn: a page drawn plain first rewraps under
        # the reader as each styled batch arrives.
        await owner.prepare_fragments(prepared.fragments_in_range, current,
                                      selected=owner.selected_categories, target=owner)
        if not current():
            raise _DrawingStopped
        async with AsyncExitStack() as acquisition:
            acquisition.push_async_callback(owner.remove_children, (view,))
            await end.mount(owner, view, pages)
            if not current():
                raise _DrawingStopped
            yield view
            acquisition.pop_all()

    def set_categories(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.visible_categories = selected
        self.range_changed()

    async def select_range(
        self, selected: slice, current: Callable[[], bool],
    ) -> bool:
        if not current():
            return False
        window = self.query_ancestor(LineHistory).window
        async with window.history_lock:
            if not current():
                return False
            async with window.preserve_history():
                return self.prepared.replace_range(self, selected, current)

class DrawsBusMessages:
    """The fragments the loaded pages draw, and whether they include a bus message, scrolled into view or not."""

    pages: deque[TranscriptPageView]

    @property
    def fragments_in_range(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.prepared.fragments_in_range)

    def draws(self, message: BusMessage) -> bool:
        return any(fragment.draws(message) for fragment in reversed(self.fragments_in_range))


class LineHistory(DrawsBusMessages, SourceNotifications, OpensLinks, TranscriptSourcePreparation, ConversationEntry, VerticalGroup):
    """History drawn as lines, a bounded range of pages at a time.

    It owns paging in both directions, lookahead, trimming, the jump to the newest page and the reader's position.
    Its saved rows fade as each fragment arrives (`repaint`). A subclass says what its source is:
    `TranscriptHistory` for a saved transcript, `WireHistory` for a channel or direct conversation.
    """

    CACHE_SUBTREE_GEOMETRY = True
    DEFAULT_BUDGET = PresentationBudget(max_items=240)


    def owns_projection(self, projection: ProjectedTranscriptHistory) -> bool:
        return self.filter.owns_projection(projection)

    def draws_projection(self, projection: ProjectedTranscriptHistory) -> bool:
        return self.state.can_draw and self.owns_projection(projection)

    def apply_message_filter(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.projection_changed()

    def starts_agent_activity(self, boundary) -> bool:
        return False

    @cached_property
    def block_cursor(self):
        return FragmentBlockCursor(self)

    def __init__(self, prepared: PreparedTranscriptPage, page_source: PreparedPageSource,
                  *, notification_view: HistoryNotifications, budget: PresentationBudget = DEFAULT_BUDGET,
                  source_state: TranscriptState) -> None:
        self.notification_view = notification_view
        super().__init__(source_state=source_state, page_source=page_source)
        self.budget = budget
        self.pages = deque([TranscriptPageView(
            prepared, batch_size=self.budget.batch_items,
        )])
        self.older = HistoryEdge("↑ Earlier history loads as you scroll")
        self.older.tooltip = "Click or press Enter to load earlier history, including in In/out only mode"
        self.newer = JumpToLatest("↓ Jump to latest")
        self.filter = FilterState.for_selection(self)
        self._fragment_budget = self.budget.max_items

    async def park_document(self) -> PreparedPageSource:
        """Stop reading and hand the drawn pages to their reader, to be rebuilt when the tab returns."""
        await self.retire_source(parked=True)
        source = self.page_source
        projected = await self.filter.overlay.park_document()
        pages = tuple(page.prepared for page in self.pages)
        await source.runtime.run_thread(source.measure_held, pages, projected)
        source.park(pages, projected)
        return source

    def acquire_document(self) -> None:
        """The rebuilt pages are mounted: the reader no longer keeps them for a later rebuild."""
        self.page_source.release_held()
        self.filter.overlay.acquire_document()

    def resume_source(self) -> None:
        super().resume_source()
        self.filter.overlay.resume_source()

    async def prepare_fragments(self, fragments: tuple[TranscriptFragment, ...],
                                current: Callable[[], bool], *,
                                selected: frozenset[type[MessageCategory]],
                                target: LineHistory | Contents) -> None:
        """Render against the native destination, including before history is mounted."""
        width, theme = target.line_width, self.app.colours.line_theme
        if width <= 0:
            return
        pending = (waiting for fragment in fragments if fragment.shown_in(selected)
                   for waiting in fragment.lines_for(width, theme).unstyled(fragment))
        while current():
            batch = tuple(islice(pending, self.budget.batch_items))
            if not batch:
                return
            ready = await TranscriptLinesBatchRenderTask.render_for(target,
                (LinePreparation(fragment.line_blocks, theme) for fragment in batch))
            if not current():
                return
            for fragment, (task, lines) in zip(batch, ready):
                task.hold(target, fragment, lines)

    @property
    def line_width(self) -> int:
        """Native content width used by preparation and page measurement."""
        return max(0, self.size.width - self.scrollbar_gutter.width)

    async def prepare_rows(self, current: Callable[[], bool], *, window: HistoryWindow,
                           target: Contents, selected: frozenset[type[MessageCategory]],
                           rows_needed: int) -> None:
        """Prepare the destination before its first native layout can expose raw rows."""
        window.prepare_history(self)
        if target.line_width <= 0:
            return
        _, limit = window.latest_limits(self.budget)
        position = window.reader_position
        rows_needed, _ = await position.prepare(
            self, current, target, selected, rows_needed, limit,
        )
        await self.filter.prepare_rows(
            current, window=window, target=target, rows_needed=max(0, rows_needed),
        )

    @property
    def fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.prepared.fragments)

    def read_fragments(self) -> tuple[TranscriptFragment, ...]:
        """Fragments whose own text has a row in the viewport."""
        if not self.is_attached or not self.can_draw_on_screen:
            return ()
        return tuple(
            fragment for page in self.visible_pages() for fragment, rows, lines in page.visible_rows(self.window)
            if (text := fragment.text_rows(lines)) and rows.start < text.stop and text.start < rows.stop)

    def visible_pages(self) -> list[TranscriptPageView]:
        """This history's laid-out pages, in row order, without visiting retained pages."""
        visible = self.screen._compositor.visible_widgets
        return sorted((page for page in self.pages if page in visible and page.parent is self),
                      key=lambda page: visible[page][0].y)

    def visible_fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.visible_pages() for fragment in page.visible_fragments(self.window))

    # What a fragment shows

    def _show(self, changes: list[tuple[TranscriptFragment, Shown]]) -> Awaitable[None]:
        """Record requested state before scheduling; keep the old measured rows painted."""
        captured = [(fragment, shown, fragment._lines) for fragment, shown in changes]
        return self._draw_changes([(fragment, shown, previous) for fragment, shown, previous in captured
                                   if fragment.request_show(shown)])

    async def _draw_changes(self, changes: list[tuple[TranscriptFragment, Shown, RowAcquisition]]) -> None:
        """Prepare captured states, then publish only those still requested."""
        changes = [(fragment, shown, previous) for fragment, shown, previous in changes
                   if fragment.shown is shown]
        if not changes:
            return
        width, theme = self.line_width, self.app.colours.line_theme
        in_range = {fragment.key for fragment in self.fragments_in_range}
        drawn = [(fragment, shown, previous) for fragment, shown, previous in changes
                 if fragment.key in in_range and width > 0]
        rendered = await TranscriptLinesBatchRenderTask.render_for(self,
            (LinePreparation(fragment.line_blocks, theme) for fragment, _shown, _previous in drawn),
            previous=(previous for _fragment, _shown, previous in drawn))
        if not self.state.can_draw:
            return
        async with self.window.preserve_history():
            if not self.state.can_draw:
                return
            # A fragment still showing the requested state changes; a drawn one also holds its rows.
            undrawn = {fragment.key for fragment, shown, _previous in changes
                       if fragment.shown is shown} - {fragment.key for fragment, _shown, _previous in drawn}
            changed = undrawn | {fragment.key for (fragment, shown, _previous), (request, lines) in zip(drawn, rendered)
                                 if fragment.shown is shown and request.hold(self, fragment, lines)}
            for page in self.pages:
                held = [fragment for fragment in page.prepared.fragments_in_range if fragment.key in changed]
                if held:
                    page.lines_replaced(held)
        self.window.check_follow()

    def page_holding(self, key: FragmentKey) -> TranscriptPageView:
        """The loaded page holding this source occurrence; absence is an invalid request."""
        for page in self.pages:
            if any(candidate.key == key for candidate in page.prepared.fragments_in_range):
                return page
        raise FragmentNotLoaded("No loaded page holds the requested fragment")

    def show_details(self, page: TranscriptPageView, fragment: TranscriptFragment, shown: Shown) -> None:
        """Prepare this occurrence's disclosure; retirement never selects a replacement."""
        page.hold_fragment_top(self.window, fragment.key)
        page.run_worker(self._show([(fragment, shown)]), group="message-details")

    def can_expand(self) -> bool:
        return self.block_cursor.current.expandable()

    def is_block_expanded(self) -> bool:
        return self.block_cursor.current.expanded()

    def _set_selected_details(self, details_open: bool) -> None:
        for fragment in self.block_cursor.selected_fragments:
            self.show_details(self.page_holding(fragment.key), fragment,
                              replace(fragment.shown, details_open=details_open))

    def expand_block(self) -> None:
        self._set_selected_details(True)

    def collapse_block(self) -> None:
        self._set_selected_details(False)

    @property
    def drawn_fragments(self) -> tuple[TranscriptFragment, ...]:
        """Every fragment the pages draw rows for, oldest first."""
        return tuple(fragment for page in self.pages for fragment in page.drawn_fragments)

    def fragment_placement(self, fragment: TranscriptFragment) -> UndrawnFragment:
        """The page that draws a fragment and its rows there, or that none does."""
        return next((placement for page in self.pages
                     if (placement := page.fragment_placement(fragment)).draws), UNDRAWN)

    def draws_fragment(self, fragment: TranscriptFragment) -> bool:
        return self.fragment_placement(fragment).draws

    def fragment_under_mouse(self, widget: Widget) -> FragmentLocation:
        """The fragment drawn under the pointer, when `widget` is one of this history's pages."""
        return next((page.fragment_under_mouse() for page in self.pages if page is widget), UnloadedFragment())

    def fragment_shown(self, fragment: TranscriptFragment) -> Unplaced:
        """Where the screen shows a fragment's rows; unplaced while its page is off screen."""
        return self.fragment_placement(fragment).shown()

    def show_fragment(self, fragment: TranscriptFragment) -> None:
        """Scroll just far enough that a fragment's rows are on screen, its first row before its last."""
        self.fragment_placement(fragment).show(self)

    async def reveal_message_head(
        self, fragment: TranscriptFragment, selected: Callable[[], bool],
    ) -> TranscriptFragment:
        """Prepare one viewport at the original message's head, not its clicked render part.
        The fragment the cursor rests on after: the head, or the clicked part when the head stays put."""
        page = self.page_holding(fragment.key)
        original = page.prepared
        first = next(index for index, part in enumerate(original.fragments)
                     if part.source_identity == fragment.source_identity)
        head = original.fragments[first]
        window = self.window
        head_placement = self.fragment_placement(head)
        if head_placement.head_on_screen(window):
            return fragment
        snapshot = self.source_snapshot()
        revision, width = window.scroll_revision, self.line_width
        current = lambda: (snapshot.current(self) and selected()
                           and window.scroll_revision == revision and self.line_width == width
                           and page in self.pages)
        staged = original.for_view()
        staged.set_fragment_range(slice(first, first))
        height = window.scrollable_content_region.height
        await staged.prepare_rows(
            self, current, target=self, selected=self.selected_categories, end=NEWER_END,
            boundary=first, rows_needed=height + 1, limit=max(self.fragment_limit, height + 1),
        )
        if not current():
            return fragment
        theme = self.app.colours.line_theme
        message_height = sum(part.lines_for(width, theme).height for part in staged.fragments_in_range
                             if part.source_identity == fragment.source_identity)
        if not head_placement.head_hidden(window, message_height):
            return fragment
        # A head with no drawn child has no row to place the reader on.
        return await head.lines_for(width, theme).block_span(lambda span: span.drawn).placed_by(
            partial(self._place_reader_at_head, head, fragment, page, staged, current),
            partial(settled, fragment))

    async def _place_reader_at_head(self, head: TranscriptFragment, fragment: TranscriptFragment,
                                    page: TranscriptPageView, staged: PreparedTranscriptPage,
                                    current: Callable[[], bool], span: BlockSpan) -> TranscriptFragment:
        """Swap in the staged range and hold the reader on the head's first drawn child."""
        window = self.window
        async with window.history_lock:
            if not current():
                return fragment
            async with window.preserve_history():
                if not page.prepared.replace_range(page, slice(staged.start, staged.stop), current):
                    return fragment
                window.release_anchor()
                window.reader_position = FragmentPosition(head.key, 0, span.height, block=span.index)
                self._update_edges()
        return head

    @property
    def source_identity(self):
        return self.page_source.reload_key(), self.page_source.through, self.selected_categories

    def paging_window(self):
        # What an edge check decides from: the saved extent, the pages'
        # loaded ranges and the filter. A check that finds a read running is
        # skipped, and the read asks again only when one of these changed
        # under it, so a filter chosen during a read must count.
        return self.page_source.through, self.filter, tuple(
            (page.prepared.page.before, page.prepared.page.after, page.prepared.capture_range()) for page in self.pages)

    def capture_reader_ranges(self) -> tuple[PageFragmentRange, ...]:
        """Retain the original source ranges that a returning reader needs."""
        return tuple(page.prepared.capture_range() for page in self.pages)

    def set_reader_ranges(self, ranges) -> None:
        for page in self.pages:
            for page_range in ranges:
                page.prepared.restore_range(page_range)
        self.filter.overlay.set_reader_ranges(ranges)

    async def restore_reader_ranges(self, ranges, current: Callable[[], bool]) -> bool:
        """A kept native view loads the same source suppliers before paint.

        Parked reconstruction sets source demand before composition. A live
        page still has its preceding children, so it uses the original range
        transaction to join new membership before evaluating reader placement.
        """
        for page in self.pages:
            for page_range in ranges:
                if page_range.page() is not page.prepared:
                    continue
                if not current():
                    return False
                if (page.prepared.start == page_range.start and page.prepared.stop == page_range.stop
                        and len(page.prepared.fragments_in_range) == len(page_range.members)
                        and all(fragment is member for fragment, member in
                                zip(page.prepared.fragments_in_range, page_range.members))):
                    continue
                await self.prepare_fragments(page_range.members, current,
                                             selected=self.selected_categories, target=self)
                if not await page.select_range(slice(page_range.start, page_range.stop), current):
                    return False
        if not await self.filter.overlay.restore_reader_ranges(ranges, current):
            return False
        if not current():
            return False
        self._update_edges()
        return True

    def projection_changed(self) -> None:
        self.filter = self.filter.changed()
        self._update_edges()
        self.window.prepare_history(self)
        self.request_preparation()

    def invalidate_projection(self) -> None:
        self._generation += 1

    def projected_source(self, selected) -> ProjectedTranscriptSource:
        page = self.pages[0]
        return ProjectedTranscriptSource(
            page.prepared, self.page_source, RangeCategoryProjection(
                selected, PageFragmentRange(ref(page.prepared), 0, page.prepared.start,
                                           page.prepared.fragments[:page.prepared.start])),
        )

    @property
    def fragment_limit(self) -> int:
        # Screen rows are not fragment counts: one prepared fragment may contain
        # a dozen lines or a whole indivisible Markdown block. Grow with the
        # number actually visible, keeping two loaded batches in reserve.
        return max(self._fragment_budget, self._visible_fragment_budget())

    def _visible_fragment_budget(self) -> int:
        return self.budget.item_limit(len(self.visible_fragments()))

    @property
    def fragment_count(self) -> int:
        return sum(page.prepared.stop - page.prepared.start for page in self.pages)

    @property
    def retained_source_bytes(self) -> int:
        return sum(fragment.retained_bytes for fragment in self.fragments_in_range)

    def compose(self) -> ComposeResult:
        yield self.older
        yield from self.filter.overlay.projection_widgets()
        for page in self.pages:
            page.visible_categories = self.selected_categories
            yield page
        yield self.newer

    async def on_mount(self) -> None:
        await self._finish_mount()
        self.state.mounted(self)

    def load_initial_page(self) -> None:
        self.request_latest(LatestPosition.hold(self.window))

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        """A page joined what this history draws."""

    def extend_source(self, through: TranscriptCursor) -> None:
        """The source now reaches `through`; the drawn pages stay as they are."""
        self._generation += 1
        self.page_source.through = through
        edge = self.pages[-1]
        edge.prepared.page = replace(edge.prepared.page, has_newer=edge.prepared.page.after != through)
        self._update_edges()

    async def _finish_mount(self) -> None:
        await self._page_added(self.pages[0].prepared.page, self.pages[0].prepared.fragments)
        self._update_edges()
        self.observe_source()

    def _update_edges(self) -> None:
        shown = bool(self.selected_categories)
        older, newer = shown and self.filter.older_visible, shown and NEWER_END.visible_more(self)
        if (older, newer) != (self.older.display, self.newer.display):
            # The edge rows are above and below the reader's.
            self.window.keep_reader()
            self.older.display, self.newer.display = older, newer

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        """A saved viewer or nested pager shows every category; a conversation's history shows its filter."""
        return all_categories()

    @property
    def drawn_extent(self) -> tuple[int, int]:
        pages = [page for page in self.pages if page.line_count]
        return sum(page.line_count for page in pages), sum(page.prepared.stop - page.prepared.start for page in pages)

    def _size_updated(self, size: Size, virtual_size: Size, container_size: Size, layout: bool=True) -> bool:
        # Edges are read from this history's laid-out box. A check made
        # before layout gave it one (a filter just chosen, a first page) finds
        # none, and a history shorter than its window changes no size but its own.
        changed = super()._size_updated(size, virtual_size, container_size, layout)
        if changed:
            self.request_preparation()
        return changed

    @on(JumpToLatest.Requested)
    def on_jump(self, event: JumpToLatest.Requested) -> None:
        event.stop()
        self.window.jump_to_latest()

    @on(HistoryEdge.Requested)
    def on_earlier_history(self, event: HistoryEdge.Requested) -> None:
        event.stop()
        self.window.lookahead.request_older()
        if self.filter.active:
            self.filter.request_older()

    @property
    def drawn_tail_followed(self) -> bool:
        return not self.drawn_end_more and self.follows_source_tail

    def arrivals_began(self) -> None:
        """A burst of arrivals fades in; every row is drawn from the first frame."""
        if not self.is_on_screen:
            return  # A burst nobody sees has nothing to fade.
        # The burst is decided by the fade's phase.
        self.run_effect(NEW_TEXT)

    def hold_arrival(self, arrivals: tuple[TranscriptFragment, ...]) -> None:
        """The first shown arriving message places a following reader: from its head when it is taller than the window."""
        window = self.window
        if not window.shown:
            return
        for head in arrivals:
            page = self.page_holding(head.key)
            if head.shown_in(page.visible_categories):
                window.reader_position = window.reader_position.arrived(page, head.key)
                return

    def repaint(self, fragments: tuple[TranscriptFragment, ...] = (), *, continuing=()) -> None:
        phase = self.effect_phase(NEW_TEXT)
        if fragments:
            phase.on_new_arrival(self, NEW_TEXT, self.pages)
        positions = {fragment.arrival_position for fragment in (*fragments, *phase.keeps_arrivals(continuing))}
        for page in self.pages:
            previous = bool(page.arrivals)
            page.arrivals.intersection_update(phase.keeps_arrivals(page.arrivals))
            if positions:
                page.arrivals.update(fragment.key for fragment in page.prepared.fragments_in_range
                                     if fragment.arrival_position in positions)
            if previous or page.arrivals:
                page.refresh()

    def on_hide(self) -> None:
        for page in self.pages:
            page.arrivals.clear()

    async def _load_page(
        self, end: PageEnd,
        publication_current: Callable[[], bool] = lambda: True,
    ) -> bool:
        """Publish one readable range; report whether its edge still needs rows."""
        snapshot = self.source_snapshot()
        window = snapshot.window
        # Only an append beyond the fully drawn, followed end is an arrival.
        # Local range growth, older paging and destination restoration are not.
        followed_end = end.fresh(self)

        def current() -> bool:
            if not snapshot.current(self) or not publication_current():
                return False
            return window.follows_tail if followed_end else window.lookahead.demand.accepts_result(end)

        try:
            if not current():
                return False
            edge = end.edge(self.pages)
            page_range = edge.prepared.capture_range()
            edge_cursor = edge.prepared.page.before, edge.prepared.page.after
            demand = window.lookahead.demand
            missing = (window.lookahead.ahead_rows(window.outer_size.height) if followed_end
                       else window.lookahead.read_rows(self, end))
            local = end.can_extend(edge.prepared)
            if local:
                staged = edge.prepared.for_view()
            else:
                source = self.page_source
                if not source.has_more(end, edge.prepared.page):
                    return False
                staged = await source.get(end.adjacent(edge.prepared.page))
                demand.source_read()
                if (not await self.source_is_current(snapshot) or not current()
                        or not await source.accept_page(self, edge, staged)):
                    return False
            # Speculation warms the same scoped runtime entry as the next
            # foreground request; it does not copy decoded pages into a widget.
            window.lookahead.demand.prepare_ahead(window.lookahead, self, staged.page, end)
            await staged.prepare_rows(
                self, current, target=self, selected=self.selected_categories, end=end,
                boundary=end.edge_boundary(edge, local, staged),
                rows_needed=max(1, missing), limit=self.fragment_limit)
            if not current():
                return False
            async with window.history_lock:
                if not current():
                    return False
                if end.edge(self.pages) is not edge:
                    return False
                if edge.prepared.capture_range() != page_range:
                    return False
                protected = {fragment.key for fragment in self.visible_fragments()}
                async with window.preserve_history():
                    arrivals = self._source_state.arriving(staged, followed_end)
                    await self._extend_and_trim(edge, end, local, protected, staged, current=current)
                    self._require_can_draw()
                    self.hold_arrival(arrivals)
                    self.repaint(arrivals)
                    self.rows_published()
                    if not local:
                        await self._page_added(staged.page, staged.fragments)
            self.state.delivered(self)
            advanced = end.edge(self.pages)
            if (advanced is edge and edge.prepared.capture_range() == page_range
                    and (edge.prepared.page.before, edge.prepared.page.after) == edge_cursor):
                return False
            if followed_end or not current():
                return False
            return bool(window.lookahead.read_rows(self, end))
        except _DrawingStopped:
            return False
        finally:
            if self.state.can_draw:
                self.window.check_follow()

    async def _extend_and_trim(
        self, edge: TranscriptPageView, end: PageEnd, local: bool,
        protected: set[FragmentKey], prepared: PreparedTranscriptPage, *,
        current: Callable[[], bool],
    ) -> None:
        """Load the next range and trim fragments the reader is not seeing.

        protected holds ids of fragments that must stay loaded: the visible
        ones and those just loaded for the reader's direction of travel.
        """
        async with self.lock:
            previous_start = self.pages[0], self.pages[0].prepared.start
            overlay_visible = bool(self.filter.overlay.visible_fragments())
            protected_pages: set[TranscriptPageView] = set()
            if not prepared.fragments:
                # A nonmatching interval advances the original source span,
                # not the native tree. No empty page widget or decoded cache.
                end.advance_empty(edge.prepared, prepared)
            elif local:
                previous = {fragment.key for fragment in edge.prepared.fragments_in_range}
                if not await edge.prepared.extend(edge, prepared, current):
                    raise _DrawingStopped
                self._require_can_draw()
                protected.update(fragment.key for fragment in edge.prepared.fragments_in_range
                                 if fragment.key not in previous)
            else:
                page_range = edge.prepared.capture_range()
                async with TranscriptPageView.acquire(
                    self, prepared, end=end, pages=self.pages,
                    current=lambda: current() and edge.prepared.capture_range() == page_range,
                ) as view:
                    end.append(self.pages, view)
                protected.update(fragment.key for fragment in view.prepared.fragments_in_range)
                protected_pages.add(view)
            self._fragment_budget = limit = max(
                self.budget.item_limit(len(protected)), self._visible_fragment_budget(),
            )
            excess = self.fragment_count - limit
            while (excess > 0 or len(self.pages) > limit) and (self.fragment_count > 1 or len(self.pages) > 1):
                for side in end.eviction_order(self):
                    # A visible older projection protects the range between it
                    # and the main pages, just like a visible page.
                    if not side.can_evict(overlay_visible):
                        continue
                    evicted = side.edge(self.pages)
                    if evicted in protected_pages:
                        continue
                    members = tuple(side.eviction_fragments(evicted.prepared))
                    available = 0
                    for fragment in members:
                        if fragment.key in protected:
                            break
                        available += 1
                    if available or not members:
                        break
                else:
                    # No side has a page it may evict.
                    break
                count = evicted.prepared.stop - evicted.prepared.start
                remove_count = min(max(0, excess), available, self.fragment_count - 1)
                if remove_count >= count and len(self.pages) > 1:
                    side.pop(self.pages)
                    evicted.remove()
                    excess -= count
                else:
                    if not remove_count:
                        break
                    side.trim(evicted, min(remove_count, count))
                    excess -= remove_count
            self.filter.canonical_moved(previous_start, overlay_visible)
            self._update_edges()

class CommittedHistory(LineHistory, SnapshotPresentation):
    """A saved source block that precedes the conversation's live tail."""

    conversation_order = 0

    @property
    def commit_claim(self) -> CommitClaim:
        return RETAINED_SOURCE_CLAIM

    def accepts_commit(self, cursor: TranscriptCursor) -> bool:
        return self.page_source.accepts_commit(cursor)

    def covered_sequences(self, sequences: frozenset[int]) -> frozenset[int]:
        return frozenset(sequence for sequence in sequences if self.covers_incoming(sequence))

    def covers_outgoing(self, message: PublishedSentMessage) -> bool:
        return message.reference in self.outgoing_coverage

    def source_resumed(self) -> None:
        if self._source_state.reports_coverage:
            self.publish_core(TranscriptCoverage(tuple(self.coverage_events)))

    def publish_committed(self) -> None:
        """Acquire source ownership now; report coverage after its first painted frame."""
        self._source_state = self._source_state.publish()
        self.call_after_refresh(self.publish_coverage)
        self.request_preparation()

    def publish_coverage(self) -> None:
        if self._source_state.reports_coverage:
            self.publish_core(TranscriptCoverage(tuple(self.coverage_events)))

    @property
    def coverage_events(self) -> Iterator[TranscriptEvent]:
        return (event for page in self.pages for event in page.prepared.page.events)

    @property
    def outgoing_coverage(self):
        if self._source_state.reports_coverage:
            references = frozenset(reference for page in self.pages
                                   for reference in page.prepared.outgoing_coverage)
            return references | self.filter.overlay.outgoing_coverage
        return frozenset()

    def covers_incoming(self, sequence: int) -> bool:
        if not self._source_state.reports_coverage:
            return False
        if self.page_source.through.covers_incoming(sequence):
            return True
        if sequence in TranscriptCoverage(tuple(self.coverage_events)).sequences:
            return True
        return self.filter.overlay.covers_incoming(sequence)

    def covers_input(self, started: InputStartedUpdate) -> bool:
        """Whether the loaded saved pages hold the input Core started under this identity."""
        return (self._source_state.reports_coverage
                and started.native_id in TranscriptCoverage(tuple(self.coverage_events)).native_inputs)

    def retain_committed(self, through: TranscriptCursor) -> None:
        """Extend access to saved source without moving the displayed page window."""
        if not self.accepts_commit(through):
            raise ValueError("Commit replaces or rewinds the retained source")
        self.extend_source(through)

class ConversationHistory[ViewT: "Conversation"](LineHistory):
    """A conversation owns its source binding and initial history state."""

    page_source: ReplaceablePageSource

    def __init__(self, *args, view: ViewT, **kwargs) -> None:
        self.view = view
        super().__init__(*args, **kwargs)

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        return self.view.visible_categories

    async def show_newest(self, request: ReplacementViewportRequest, *,
                          arrivals: tuple[TranscriptFragment, ...] = (),
                          publication_current: Callable[[], bool] = lambda: True) -> bool:
        """Replace the drawn source, retaining the followed tail's active arrivals."""
        retained = (tuple(fragment for page in self.pages for fragment in page.prepared.fragments_in_range
                          if fragment.key in page.arrivals)
                    if self.follows_source_tail else ())
        self._generation += 1
        published = await self.jump_latest(request, publication_current)
        if published:
            self.repaint(arrivals, continuing=retained)
        return published

    @classmethod
    def empty_source(cls, view, through):
        return ClosedHistory(through, view.app.preparation)

    @classmethod
    def empty(cls, *, view, notification_view):
        prepared = cls.empty_page()
        return cls(prepared, cls.empty_source(view, prepared.page.after),
                   view=view, notification_view=notification_view, source_state=cls.initial_state(view))


class TranscriptHistory[ViewT: "Conversation"](CommittedHistory, ConversationHistory[ViewT]):
    """The line history of a saved transcript.

    Its pages stand in for the conversation's live blocks: it reports which
    events it covers, follows the committed end of the transcript, and can be
    parked with a tab and rebuilt from what was parked.
    """

    @classmethod
    def initial_state(cls, view):
        return view.query_ancestor(SessionScope).thread_identity.transcript_state()

    @classmethod
    def empty_page(cls):
        return PreparedTranscriptPage.empty(UnreadTranscriptPage())

    @classmethod
    def empty_source(cls, view, through):
        return SavedHistory(view.transcript.get_transcript_page, through, view.app.preparation)

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        if self._source_state.reports_coverage:
            view = self.view
            view.transcript.binding.covered(
                view.transcript, TranscriptCoverage(page.events), self).call_when_ready(view)

    async def restore_source(self, source: PreparedPageSource, current) -> None:
        """Put the parked pages back into the same mounted reader."""
        pages = source.held_pages
        if not pages or source.closed:
            raise ValueError("No kept transcript range")
        await self.retire_source()
        retired = tuple(self.pages)
        self.page_source = source
        self._source_state = ParkedSourceTranscript(LiveTranscript())
        self.pages = deque(TranscriptPageView(page, batch_size=self.budget.batch_items)
                           for page in pages)
        self.filter = FilterState.for_selection(self)
        projected = source.projection_source
        if projected.held_pages:
            from toad.transcript_filter import Filtered
            projection = ProjectedTranscriptHistory.from_source(projected, owner=self)
            self.filter = Filtered(self, projection)
        await self.notification_view.prepare_history(self, current, window=self.window)
        if current():
            await self.mount(*self.pages, before=self.newer)
            await self.remove_children(retired)
            self.acquire_document()

class NoProjectionOwner:
    """The source view a projection outlived: it owns and draws no projection."""

    def owns_projection(self, projection: ProjectedTranscriptHistory) -> bool:
        return False

    def draws_projection(self, projection: ProjectedTranscriptHistory) -> bool:
        return False


NO_PROJECTION_OWNER = NoProjectionOwner()


class ProjectedTranscriptHistory(CommittedHistory):
    """A filtered source view with the ordinary pager's loading and eviction policy."""

    def __init__(self, owner: LineHistory, source: ProjectedTranscriptSource,
                 prepared: PreparedTranscriptPage) -> None:
        self._projection_owner = ref(owner)
        super().__init__(prepared, source, budget=owner.budget,
                         notification_view=owner.notification_view, source_state=LiveTranscript())

    def _owner(self) -> LineHistory | NoProjectionOwner:
        """The weak reference decoded once: the live source view, or none."""
        return self._projection_owner() or NO_PROJECTION_OWNER

    @classmethod
    def from_source(cls, source: ProjectedTranscriptSource, *, owner: LineHistory):
        if not source.held_pages or source.closed:
            raise ValueError("No kept projected range")
        history = cls(owner, source, source.held_pages[0])
        history.pages.extend(TranscriptPageView(
            page, batch_size=owner.budget.batch_items,
        ) for page in source.held_pages[1:])
        history._source_state = ParkedSourceTranscript(LiveTranscript())
        return history

    @property
    def older_page_available(self) -> bool:
        return self.source_ready and OLDER_END.visible_more(self)

    def request_older(self) -> None:
        if self.older_page_available:
            self.request_page(OLDER_END)

    async def load_older(self) -> None:
        if self.older_page_available:
            await self.reserve_source_work().execute(self, partial(self._prepare_edge, OLDER_END))

    @property
    def state(self) -> TranscriptState:
        return super().state.for_projection(self, self._owner())

    @property
    def follows_source_tail(self) -> bool:
        # This window is a historical prefix, not the live main tail.
        return False

    def projection_widgets(self):
        return (self,)

    def reads(self, source) -> bool:
        return self.page_source is source

    @property
    def coverage_events(self) -> Iterator[TranscriptEvent]:
        return (event for page in self.pages for fragment in page.prepared.fragments for event in fragment.events)

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        owner = self._owner()
        if owner.owns_projection(self):
            await owner._page_added(replace(page, events=tuple(
                event for fragment in fragments for event in fragment.events
            )), fragments)
