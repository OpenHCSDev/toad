"""Bounded, cursor-paged saved history; all transcript interpretation is model-owned."""

from __future__ import annotations

from abc import ABC, abstractmethod
from bisect import bisect_right
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from functools import cached_property, partial
from itertools import accumulate, chain, islice
from typing import TYPE_CHECKING, ClassVar, Final
from weakref import ref

from agent_comms.execution.transcript_sources import TranscriptCursor
from agent_comms.nominal.fold import Absorbs, Accumulates, Fold
from agent_comms.transcript.transcript_events import TranscriptEvent
from agent_comms.transcript.transcripts import TranscriptPage
from agent_comms.ui_model.message_category import (
    MessageCategory,
    all_categories,
)
from metaclass_registry.mro_dispatch import handles
from rich.style import Style as RichStyle
from textual import on
from textual._compositor import IntrinsicSubtreeGeometry
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual._paint_state import PaintState
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.events import Hide, Mount
from textual.geometry import Region, Size
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker

from toad.block_navigation import ConversationEntry, FragmentBlockCursor
from toad.client.history_coverage import ReportsCoveredPages
from toad.client.committed_history import CommittedHistoryBase
from toad.client.history_pager import ConversationPager, DrawsBusMessages, HistoryPager, NativePager
from toad.frame_presentation import ARRIVAL, ArrivalRun
from toad.entry_placement import EntryPlacement
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
from toad.transcript_filter import Filtered, FilterState, SeekingFilter
from toad.transcript_preparation import SavedTranscript
from toad.client.prepared_pages import (
    ClosedHistory,
    PageFragmentRange,
    PreparedPageSource,
    PreparedTranscriptPage,
    ProjectedTranscriptSource,
    RangeCategoryProjection,
    ReplaceablePageSource,
    UnreadTranscriptPage,
)
from toad.transcript_source_preparation import TranscriptSourcePreparation
from toad.client.history_state import (
    LiveTranscript,
    ParkedSourceTranscript,
    TranscriptState,
)
from toad.widget_actions import Activates
from toad.widgets.history_anchor import HistoryWindow
from toad.client.reader_position import (
    FragmentLocation,
    FragmentNotLoaded,
    FragmentPosition,
    ReaderPage,
    ReaderPosition,
    UnloadedFragment,
)
from toad.widgets.linked_rows import (
    HorizontalRows,
    OpensLinks,
    ReferenceRendering,
    selection_painted,
)
from toad.client.history_notifications import HistoryNotifications, SourceNotifications
from toad.client.history_preparation import NEWER_END, OLDER_END
from toad.widgets.presentation_window import UNPLACED, PointerRows, Unplaced, arranged
from toad.client.history_pager import PresentationBudget
from toad.widgets.selection import HoverSelection
from toad.widgets.transcript_fragments import TranscriptFragment
from toad.client.fragment_states import (
    DrawnFragment,
    FragmentSpan,
    LaidOut,
    MeasureAgain,
    NOT_LAID_OUT,
    NotLaidOut,
    RepaintRows,
    RowChange,
    UNDRAWN,
    UndrawnFragment,
)
from toad.client.fragments import FragmentDetails, FragmentKey, Shown
from toad.widgets.transcript_lines import (
    BlockLines,
    BlockSpan,
    LinePreparation,
    Lines,
    LineTarget,
    RowAcquisition,
    TranscriptLinesBatchRenderTask,
)


if TYPE_CHECKING:

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
    ReaderPage,
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

    @on(Mount)
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
            strip = history.effect_phase(ARRIVAL).paint(history, ARRIVAL, strip, self.arrival_position(y))
        return selection_painted(self, self.on_background(strip, paint, y), y)

    @property
    def arrival_run(self) -> ArrivalRun:
        """The rows this page draws for its arriving fragments, in drawing order."""
        return ArrivalRun(tuple(
            range(first, first + lines.height)
            for fragment, first, lines in self._layout if fragment.key in self.arrivals))

    def arrival_position(self, y: int) -> float:
        """How far row `y` is through this page's arriving rows: 0 the first, 1 the last."""
        return self.arrival_run.row_position(y)

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
    def drawn_for(cls, owner: LineHistory, prepared: PreparedTranscriptPage) -> TranscriptPageView:
        view = cls(prepared)
        view.visible_categories = owner.selected_categories
        view.display = False
        return view

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


class LineHistory(DrawsBusMessages, SourceNotifications, OpensLinks, TranscriptSourcePreparation, ConversationEntry, LineTarget, VerticalGroup, NativePager):
    """History drawn as lines, a bounded range of pages at a time.

    It owns paging in both directions, lookahead, trimming, the jump to the newest page and the reader's position.
    Its saved rows fade as each fragment arrives (`repaint`). A subclass says what its source is:
    `TranscriptHistory` for a saved transcript, `WireHistory` for a channel or direct conversation.
    """

    # A restricted category selection is shown as a projection read and mounted over the pages.
    restricted_filter = SeekingFilter

    page_view_type = TranscriptPageView
    CACHE_SUBTREE_GEOMETRY = True

    def subtree_geometry_resource(self, *, visible_only: bool):
        """Prepared pages retain their content layout independently of scrolling."""
        return IntrinsicSubtreeGeometry

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
                  *, notification_view: HistoryNotifications, budget: PresentationBudget = HistoryPager.DEFAULT_BUDGET,
                  source_state: TranscriptState) -> None:
        self.notification_view = notification_view
        super().__init__(source_state=source_state, page_source=page_source)
        self.budget = budget
        self.pages = deque([self.page_view_type(
            prepared, batch_size=self.budget.batch_items,
        )])
        self.older = HistoryEdge("↑ Earlier history loads as you scroll")
        self.older.tooltip = "Click or press Enter to load earlier history, including in In/out only mode"
        self.newer = JumpToLatest("↓ Jump to latest")
        self.filter = FilterState.for_selection(self)
        self._fragment_budget = self.budget.max_items

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

    def visible_pages(self) -> list[TranscriptPageView]:
        """This history's laid-out pages, in row order, without visiting retained pages."""
        visible = self.screen._compositor.visible_widgets
        return sorted((page for page in self.pages if page in visible and page.parent is self),
                      key=lambda page: visible[page][0].y)

    def read_ahead(self, work: Callable[[], Awaitable[object]]) -> None:
        # The existing runtime owns the single decoded/prepared result.
        # This native worker only waits for that original bounded work;
        # foreground paging shares it, without a page store in the widget.
        self.run_worker(work, group="transcript-read-ahead", exclusive=True, exit_on_error=False)

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

    def projected_source(self, selected) -> ProjectedTranscriptSource:
        page = self.pages[0]
        return ProjectedTranscriptSource(
            page.prepared, self.page_source, RangeCategoryProjection(
                selected, PageFragmentRange(ref(page.prepared), 0, page.prepared.start,
                                           page.prepared.fragments[:page.prepared.start])),
        )

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

    @on(Mount)
    async def on_mount(self) -> None:
        await self._finish_mount()
        self.state.mounted(self)

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

    def arrivals_began(self) -> None:
        """A burst of arrivals comes in row after row, each row fading in."""
        if not self.is_on_screen:
            return  # A burst nobody sees has nothing to fade.
        # The burst is decided by the cascade's phase.
        self.run_effect(ARRIVAL)

    def cascade_runs(self) -> Iterable[int]:
        """One run per page: each page's arriving rows cascade across themselves."""
        return (page.arrival_run.cascade_rows() for page in self.pages)

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
        phase = self.effect_phase(ARRIVAL)
        if not fragments and self.is_attached:
            # A clock tick: a following reader goes down with the rows as they rise.
            self.frame_moved()
        if fragments:
            phase.on_new_arrival(self, ARRIVAL, self.pages)
        positions = {fragment.arrival_position for fragment in (*fragments, *phase.keeps_arrivals(continuing))}
        for page in self.pages:
            previous = bool(page.arrivals)
            page.arrivals.intersection_update(phase.keeps_arrivals(page.arrivals))
            if positions:
                page.arrivals.update(fragment.key for fragment in page.prepared.fragments_in_range
                                     if fragment.arrival_position in positions)
            if previous or page.arrivals:
                page.refresh()

    @on(Hide)
    def on_hide(self) -> None:
        for page in self.pages:
            page.arrivals.clear()


class CommittedHistory(LineHistory, CommittedHistoryBase):
    """A saved source block that precedes the conversation's live tail. The behaviour body
    is on `client/committed_history.py:CommittedHistoryBase`; this class pairs it with
    Textual's `LineHistory` so TUI gets Textual-widget bases alongside the shared body.
    Qt's `qt/history.py:QtTranscriptHistory` is the parallel pairing on the Qt side."""

class ConversationHistory[ViewT: "Conversation"](LineHistory, ConversationPager):
    """A conversation owns its source binding and initial history state."""

    page_source: ReplaceablePageSource

    def __init__(self, *args, view: ViewT, **kwargs) -> None:
        self.view = view
        super().__init__(*args, **kwargs)

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        return self.view.visible_categories

    @classmethod
    def empty_source(cls, view, through):
        return ClosedHistory(through, view.app.preparation)

    @classmethod
    def empty(cls, *, view, notification_view):
        prepared = cls.empty_page()
        return cls(prepared, cls.empty_source(view, prepared.page.after),
                   view=view, notification_view=notification_view, source_state=cls.initial_state(view))


class TranscriptHistory[ViewT: "Conversation"](CommittedHistory, ConversationHistory[ViewT], ReportsCoveredPages):
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
        from toad.widgets.transcript_fragments import TEXTUAL_FRAGMENT_CLASSES
        return SavedTranscript(view.transcript.get_transcript_page, through, view.app.preparation,
                               fragments=TEXTUAL_FRAGMENT_CLASSES)

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        self.coverage.page_added(self, page)

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
