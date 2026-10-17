"""Bounded, cursor-paged saved history; all transcript interpretation is model-owned."""

from __future__ import annotations
from toad.block_navigation import ConversationBlock, FragmentBlockCursor

from toad.widgets.message_filter import OtherCategory

import asyncio
from bisect import bisect_right
from collections import deque
from contextlib import ExitStack, asynccontextmanager
from dataclasses import replace
from functools import cached_property, partial
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import TYPE_CHECKING
from weakref import ref

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.ui_model.observation import ReadNotifications
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent, ContextTranscript, UserTranscript, IncomingTranscript, AgentTextTranscript, SentTranscript,
    ThinkingTranscript,
)
from textual import events, on
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.geometry import Region
from textual.message import Message
from textual.selection import Selection
from textual._activation import PrimaryActivation
from textual.widget import Widget
from textual.walk import walk_depth_first
from textual._paint_state import PaintState
from textual.strip import Strip
from textual.widgets import Static

from toad.transcript_filter import TranscriptFilter
from toad.transcript_state import TranscriptState, LiveTranscript, ProvisionalTranscript, ParkedSourceTranscript, LatestViewportRequest
from toad.transcript_source_preparation import TranscriptSourcePreparation, _DrawingStopped
from toad.transcript_preparation import (
    RangeCategoryProjection, PageRequest, PreparedPageSource, PreparedTranscriptPage, PageFragmentRange, TranscriptPageBuffer,
    ProjectedTranscriptSource,
)
from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from toad.widgets.message_divider import AgentActivityDivider, MessageClock
from toad.frame_presentation import Animated
from toad.widgets.selection import HoverSelection
from rich.style import Style as RichStyle
from ui_theme.effects import NEW_TEXT, Mix
from toad.widgets.presentation_window import PresentationBudget
from toad.line_blocks import ToggleDetails
from toad.message_rows import MessageRow
from toad.markdown_links import ReferenceRendering
from toad.widgets.message_notifications import HistoryNotifications
from toad.widgets.transcript_lines import (
    HorizontalRows, Lines, LinePreparation, OpensMessageNames, PreparedLines, TranscriptLinesBatchRenderTask, TranscriptLinesRenderTask,
    selection_painted,
)
from toad.widgets.committed_presentation import CommittedHistory, TranscriptInputClaim
from toad.widgets.history_anchor import HeldReaderDestination, HistoryWindow, LatestPosition
from toad.widgets.message_filter import (
    all_categories, CategorizedBlock, MessageCategory, apply_block_filter,
)
from toad.widgets.transcript_fragments import (
    Shown, TranscriptFragment, transcript_fragments,
)

if TYPE_CHECKING:
    from toad.widgets.conversation import Contents, Conversation

class HistoryEdge(PrimaryActivation, Static, can_focus=True):
    DEFAULT_CSS = "HistoryEdge { height: 1; color: $text-muted; pointer: pointer; }"
    BINDINGS = [("enter,space", "earlier", "Earlier history")]

    class Requested(Message):
        pass

    @property
    def primary_activation(self):
        return self.action_earlier

    def action_earlier(self) -> None:
        self.post_message(self.Requested())

    def on_click(self, event) -> None:
        if event.button == 1:
            event.stop()
            self.action_earlier()

class JumpToLatest(HoverSelection, PrimaryActivation, Static, can_focus=True):
    highlighted_text_style = RichStyle(bold=True)
    BINDINGS = [("enter,space", "jump", "Jump to latest")]
    DEFAULT_CSS = "JumpToLatest { height: 1; color: $text-secondary; pointer: pointer; }"

    class Requested(Message):
        pass

    @property
    def primary_activation(self):
        return self.action_jump

    def action_jump(self) -> None:
        self.post_message(self.Requested())

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.action_jump()

class TranscriptPageView(ReferenceRendering, Animated[Mix], HorizontalRows, Widget):
    """One transcript page, drawn as its admitted fragments' prepared lines.

    Fragments never become widgets. Styled rows come from the render worker
    processes; until they arrive a fragment draws its plain wrapped text.
    A page that arrived on the live tail rises out of the background.
    """

    DEFAULT_CSS = "TranscriptPageView { height: auto; overflow-x: auto; overflow-y: hidden; }"
    text_fades = (NEW_TEXT,)
    RENDER_BATCH = 8

    def __init__(self, prepared: PreparedTranscriptPage, *, newest: bool = True,
                 batch_size: int = PreparedTranscriptPage.BATCH, fresh: bool = False):
        self.fresh = fresh
        self.prepared = prepared
        self.visible_categories = all_categories()
        self.prepared.configure(batch_size=batch_size, newest=newest)
        # Fragments drawn as plain text until their styled lines arrive, by identity.
        self._pending: dict[int, TranscriptFragment] = {}
        self._render_task: asyncio.Task[None] | None = None
        # The rows this page draws are the rows layout last measured: each
        # drawn fragment, its first row and its lines at the measured width.
        # A changed range draws nothing new until layout has given it a box.
        self._width = 0
        self._layout: list[tuple[TranscriptFragment, int, Lines]] = []
        self._starts: list[int] = []
        self._fragment_rows: dict[int, range] = {}
        self._height = 0
        self._measured = False
        super().__init__()

    @property
    def history(self) -> LineHistory:
        return self.query_ancestor(LineHistory)

    @property
    def line_sets(self) -> tuple[Lines, ...]:
        return tuple(lines for _, _, lines in self._layout)

    @handles(ToggleDetails)
    def toggle_details(self, link: ToggleDetails) -> None:
        """Show or hide the details of the fragment whose line was clicked."""
        history = self.history
        history.run_worker(history.toggle_details(self.fragment_under_mouse()), group="message-details")

    @property
    def page(self) -> TranscriptPage:
        return self.prepared.page

    @page.setter
    def page(self, page: TranscriptPage) -> None:
        self.prepared.page = page
        self.prepared.retained_bytes = 0

    @property
    def fragments(self) -> tuple[TranscriptFragment, ...]:
        return self.prepared.fragments

    @property
    def start(self) -> int:
        return self.prepared.start

    @start.setter
    def start(self, start: int) -> None:
        self.prepared.start = start

    @property
    def stop(self) -> int:
        return self.prepared.stop

    @stop.setter
    def stop(self, stop: int) -> None:
        self.prepared.stop = stop

    @property
    def fragments_in_range(self) -> tuple[TranscriptFragment, ...]:
        return self.fragments[self.start:self.stop]

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
        self.app.theme_changed_signal.subscribe(self, self.invalidate_lines)
        if self.fresh:
            # Once: a page moved to another parent has not arrived again.
            self.fresh = False
            self.run_effect(NEW_TEXT)

    def invalidate_lines(self, change=None) -> None:
        for fragment in self.fragments:
            fragment.invalidate_lines()
        self.range_changed()

    def on_unmount(self) -> None:
        if self._render_task is not None:
            self._render_task.cancel()

    def range_changed(self) -> None:
        """The prepared range, its lines or the filter changed; the next layout measures the new rows.

        The rows drawn stay the measured ones until then. Drawing the new
        rows in the box of the old ones would show the reader other messages
        for a frame, before layout puts them back on their row.
        """
        self._measured = False
        self.refresh(layout=True)

    def _lines(self, fragment: TranscriptFragment, width: int) -> Lines:
        theme = self.app.colours.line_theme
        lines = fragment.lines_for(width, theme)
        if lines is None:
            self._pending[id(fragment)] = fragment
            lines = fragment.plain_lines(width, self.app.colours.line_renderer)
        return lines

    def _measure(self, width: int) -> None:
        if self.is_mounted:
            self.history.window.keep_reader()
        self._width, self._measured = width, True
        self._pending.clear()
        previous = {id(fragment): lines for fragment, _first, lines in self._layout}
        visible = {id(fragment) for fragment in self.visible_fragments(self.history.window)} if previous else set()
        theme = self.app.colours.line_theme
        layout, starts, y = [], [], 0
        if width > 0:
            for fragment in self.fragments_in_range:
                if not fragment.shown_in(self.visible_categories):
                    continue
                # Offscreen rows retain their existing measured geometry.
                # A different Lines.width already expresses pending wrapping;
                # there is no second stale flag or resize cache.
                lines = previous.get(id(fragment))
                if (lines is None or id(fragment) in visible
                        or not fragment.retains_lines(lines, theme)):
                    lines = self._lines(fragment, width)
                layout.append((fragment, y, lines))
                starts.append(y)
                y += lines.height
        self._layout, self._starts, self._height = layout, starts, y
        self._fragment_rows = {id(fragment): range(first, first + lines.height) for fragment, first, lines in layout}
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
        if (visible and self._pending
                and (self._render_task is None or self._render_task.done())):
            self._render_task = asyncio.create_task(self._render_pending(), eager_start=False)

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container, viewport, width: int) -> int:
        # The admitted fragments wrapped at this width: the container's height
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
        strip = self.paint_effects(strip)
        return selection_painted(self, self.on_background(strip, paint), y)

    def fragment_row(self, fragment: TranscriptFragment) -> tuple[int, int, bool] | None:
        """A fragment's first measured row, height and whether the page draws it.

        A fragment without rows of its own (the filter hides it, or layout
        has not measured it yet) is where the next drawn fragment starts, or
        at the page's end when none follows. None when the fragment is not
        admitted here.
        """
        admitted = self.fragments_in_range
        at = next((index for index, candidate in enumerate(admitted) if candidate is fragment), None)
        if at is None:
            return None
        for candidate in admitted[at:]:
            if (rows := self._fragment_rows.get(id(candidate))) is not None:
                return rows.start, len(rows), candidate is fragment
        return self._height, 0, False

    @property
    def drawn_fragments(self) -> tuple[TranscriptFragment, ...]:
        """The fragments this page draws rows for, oldest first."""
        return tuple(fragment for fragment, _first, _lines in self._layout)

    def fragment_rows(self, fragment: TranscriptFragment) -> range | None:
        """The rows of this page that draw a fragment."""
        return self._fragment_rows.get(id(fragment))

    @property
    def screen_region(self) -> Region | None:
        """Where the screen shows this page, including the part scrolled out of view."""
        geometry = self.screen._compositor.visible_widgets.get(self)
        return None if geometry is None else geometry[0]

    def fragment_under_mouse(self) -> TranscriptFragment | None:
        if (region := self.screen_region) is None:
            return None
        row = self.app.mouse_position.y - region.y
        found = self.fragment_at(row) if 0 <= row < self._height else None
        return None if found is None else found[0]

    @property
    def tooltip(self) -> str | None:
        """The full time of the message under the pointer."""
        fragment = self.fragment_under_mouse()
        return None if fragment is None else MessageClock.recorded(fragment.timestamp).display()[1]

    def fragment_at(self, row: int) -> tuple[TranscriptFragment, int] | None:
        """The admitted fragment drawn at a row of this page, and the row within it."""
        slot = bisect_right(self._starts, row) - 1
        if slot < 0:
            return None
        fragment, first, _lines = self._layout[slot]
        return fragment, row - first

    def visible_rows(self, window) -> Iterator[tuple[TranscriptFragment, range, Lines]]:
        """Each admitted fragment in the window's viewport, with its rows that are in view."""
        # A page the viewport layout did not place is off screen; computing
        # its offset would rebuild the compositor's whole map.
        offset = window.placed_row(self)
        if offset is None:
            return
        top = int(window.scroll_y - offset)
        bottom = top + window.outer_size.height
        slot = max(0, bisect_right(self._starts, top) - 1)
        for index in range(slot, len(self._layout)):
            fragment, first, lines = self._layout[index]
            if first >= bottom:
                break
            if first + lines.height > top:
                yield fragment, range(max(0, top - first), min(lines.height, bottom - first)), lines

    def visible_fragments(self, window) -> tuple[TranscriptFragment, ...]:
        """The fragments this page draws inside the window's viewport."""
        return tuple(fragment for fragment, _rows, _lines in self.visible_rows(window))

    def _nearest_pending(self) -> list[TranscriptFragment]:
        from toad.widgets.history_anchor import HistoryWindow

        window = self.query_ancestor(HistoryWindow)
        rows = self._fragment_rows
        pending = [fragment for fragment in self.visible_fragments(window)
                   if id(fragment) in self._pending]
        # Render only visible viewport rows, nearest the reader first.
        if (offset := window.placed_row(self)) is not None:
            reader = window.scroll_y - offset
            pending.sort(key=lambda fragment: abs(rows[id(fragment)].start - reader))
        return pending[:self.RENDER_BATCH]

    async def _render_pending(self) -> None:
        while self._pending and self.is_attached:
            batch = self._nearest_pending()
            if not batch:
                return
            for fragment in batch:
                del self._pending[id(fragment)]
            theme = self.app.colours.line_theme
            ready = await TranscriptLinesBatchRenderTask.render_for(self,
                (LinePreparation(fragment.line_blocks, theme) for fragment in batch))
            await self._publish([(fragment, task, lines)
                                 for fragment, (task, lines) in zip(batch, ready)])

    async def _publish(self, ready: list[tuple[TranscriptFragment, TranscriptLinesRenderTask, LinePreparation]]) -> None:
        from toad.widgets.history_anchor import HistoryWindow

        # Native frame completion owns when new row geometry may replace the
        # measured scene. A worker finishing between layout steps must not keep
        # a reader and cancel that frame before it has ever been displayed.
        await self.screen.wait_for_refresh()
        # Holding rows does not change the page's measured layout. Retain every
        # result before opening a history change: keeping the reader can
        # interrupt an unfinished layout, even without accepted rows.
        if not any([task.hold(self, fragment, lines) for fragment, task, lines in ready]):
            return
        window = self.query_ancestor(HistoryWindow)
        async with window.preserve_history(root=self):
            self.range_changed()

    @classmethod
    @asynccontextmanager
    async def acquire(
        cls, owner: LineHistory, prepared: PreparedTranscriptPage, *,
        before: Widget, current: Callable[[], bool], fresh: bool = False,
    ) -> AsyncIterator[TranscriptPageView]:
        """Acquire the original prepared range, without selecting it a second time."""
        view = cls(prepared, fresh=fresh)
        view.visible_categories = owner.selected_categories
        # Styled before it is drawn: a page drawn plain first rewraps under
        # the reader as each styled batch arrives.
        await owner.prepare_fragments(view.fragments_in_range, current)
        if not current():
            raise _DrawingStopped
        with ExitStack() as acquisition:
            acquisition.callback(owner.remove_children, (view,))
            await owner.mount(view, before=before)
            if not current():
                raise _DrawingStopped
            yield view
            acquisition.pop_all()

    def capture_range(self) -> PageFragmentRange:
        return self.prepared.capture_range()

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
            async with window.preserve_history(root=self):
                return await self.prepared.replace_range(self, selected, current)

class LineHistory(HistoryNotifications, OpensMessageNames, TranscriptSourcePreparation, ConversationBlock, CategorizedBlock, VerticalGroup):
    """History drawn as lines, a bounded range of pages at a time.

    It owns paging in both directions, lookahead, trimming, the jump to the
    newest page and the reader's position. A subclass says what its source is:
    `TranscriptHistory` for a saved transcript, `WireHistory` for a channel or
    direct conversation.
    """

    CACHE_SUBTREE_GEOMETRY = True
    MAX_FRAGMENTS = 240
    page_buffer = TranscriptPageBuffer

    @property
    def message_category(self) -> None:
        return None

    @cached_property
    def block_cursor(self):
        return FragmentBlockCursor(self)

    def __init__(self, prepared: PreparedTranscriptPage, loader: Callable[..., Awaitable[TranscriptPage]] | None = None,
                  *, budget: PresentationBudget | None = None,
                  source_state: TranscriptState | None = None):
        super().__init__(source_state=source_state or LiveTranscript())
        self.loader, self.through = loader, prepared.page.after
        self.budget = budget or PresentationBudget(
            max_items=self.MAX_FRAGMENTS, batch_items=PreparedTranscriptPage.BATCH,
        )
        self.pages = deque([TranscriptPageView(
            prepared, batch_size=self.budget.batch_items,
        )])
        self.older = HistoryEdge("↑ Earlier history loads as you scroll")
        self.older.tooltip = "Click or press Enter to load earlier history, including in In/out only mode"
        self.newer = JumpToLatest("↓ Jump to latest")
        self.filter = TranscriptFilter(self)
        self._fragment_budget = self.budget.max_items

    @property
    def window(self) -> HistoryWindow:
        return self.query_ancestor(HistoryWindow)

    async def park_document(self) -> PreparedPageSource:
        """Stop reading and hand the drawn pages to their reader, to be rebuilt when the tab returns."""
        await self.retire_source(parked=True)
        source = self._reader()
        projection = self.filter.state.overlay
        projected = await projection.park_document() if projection is not None else None
        pages = tuple(page.prepared for page in self.pages)
        position = self.window.reader_position
        await source.runtime.run_thread(source.measure_held, pages, projected,
                                        () if position is None else position.ranges)
        source.park(pages, projected)
        return source

    @classmethod
    def from_source(cls, source: PreparedPageSource, **source_fields) -> LineHistory:
        """Rebuild a parked history from its pages; it covers no live blocks until it resumes."""
        pages = source.held_pages
        if not pages or source.closed:
            raise ValueError("No retained transcript admission")
        history = cls(pages[0], source.loader, **source_fields)
        history.through = source.through
        history._page_buffer = source
        history._source_state = ParkedSourceTranscript(LiveTranscript())
        history.pages.extend(TranscriptPageView(
            page, batch_size=history.budget.batch_items,
        ) for page in pages[1:])
        projected = source.projection_source
        if projected is not None:
            from toad.transcript_filter import Filtered
            projection = ProjectedTranscriptHistory.from_source(projected, owner=history)
            history.filter.state = Filtered(projection)
        return history

    def acquire_document(self) -> None:
        """The rebuilt pages are mounted: the reader no longer keeps them for a later rebuild."""
        if self._page_buffer is not None:
            self._page_buffer.release_held()
        if (projection := self.filter.state.overlay) is not None:
            projection.acquire_document()

    def resume_source(self) -> None:
        super().resume_source()
        if (projection := self.filter.state.overlay) is not None:
            projection.resume_source()

    async def prepare_fragments(self, fragments: tuple[TranscriptFragment, ...],
                                current: Callable[[], bool], *, selected=None,
                                target: LineHistory | Contents | None = None) -> None:
        """Render against the native destination, including before history is mounted."""
        target = self if target is None else target
        selected = self.selected_categories if selected is None else selected
        while current():
            width, theme = target.line_width, self.app.colours.line_theme
            if width <= 0:
                return
            todo = [fragment for fragment in fragments
                    if fragment.shown_in(selected) and fragment.lines_for(width, theme) is None]
            if not todo:
                return
            batch = todo[:self.budget.batch_items]
            ready = await TranscriptLinesBatchRenderTask.render_for(target,
                (LinePreparation(fragment.line_blocks, theme) for fragment in batch))
            if not current():
                return
            for fragment, (task, lines) in zip(batch, ready):
                task.hold(target, fragment, lines)

    @property
    def line_width(self) -> int:
        """Native content width; offscreen pages may retain older row widths."""
        return max(0, self.size.width - self.scrollbar_gutter.width)

    async def prepare_rows(self, current: Callable[[], bool], *, window: HistoryWindow,
                           target: Contents, selected: frozenset[type[MessageCategory]],
                           rows_needed: int) -> None:
        """Prepare the destination before its first native layout can expose raw rows."""
        window.prepare_history(self)
        if window.follows_tail and target.line_width > 0:
            _capacity, limit = window.latest_limits(self.budget)
            # A restored document keeps its original pages and older prefix.
            # Prepare only the bottom viewport; older rows warm after first paint.
            for page in reversed(self.pages):
                rows_needed -= await page.prepared.prepare_rows(
                    self, current, target=target, selected=selected,
                    boundary=len(page.fragments), older=True,
                    rows_needed=rows_needed, limit=limit,
                )
                if not current():
                    return
                limit -= page.stop - page.start
                if rows_needed <= 0 or limit <= 0:
                    break
        else:
            for page in self.pages:
                await self.prepare_fragments(page.fragments_in_range, current,
                                             selected=selected, target=target)
        await self.filter.state.prepare_rows(
            current, window=window, target=target, rows_needed=max(0, rows_needed),
        )

    @property
    def fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.fragments)

    @property
    def fragments_in_range(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.fragments_in_range)

    def read_fragments(self) -> tuple[TranscriptFragment, ...]:
        """Fragments whose own text has a row in the viewport."""
        if not self.is_attached or not self.can_draw_on_screen:
            return ()
        return tuple(
            fragment for page in self.pages for fragment, rows, lines in page.visible_rows(self.window)
            if (text := fragment.text_rows(lines)) and rows.start < text.stop and text.start < rows.stop)

    def visible_fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.visible_fragments(self.window))

    # What a fragment shows

    async def _show(self, changes: list[tuple[TranscriptFragment, Shown]]) -> None:
        """Change what fragments draw: render the new lines first, then swap them in one frame."""
        changes = [(fragment, shown) for fragment, shown in changes if shown != fragment.shown]
        if not changes:
            return
        width, theme = self.line_width, self.app.colours.line_theme
        in_range = {id(fragment) for fragment in self.fragments_in_range}
        drawn = [(fragment, shown) for fragment, shown in changes if id(fragment) in in_range and width > 0]
        rendered = await TranscriptLinesBatchRenderTask.render_for(self,
            (LinePreparation(fragment.blocks(shown), theme) for fragment, shown in drawn))
        if not self.state.can_draw:
            return
        ready = {id(fragment): result for (fragment, _shown), result in zip(drawn, rendered)}
        async with self.window.preserve_history(root=self):
            for fragment, shown in changes:
                TranscriptLinesRenderTask.show(self, fragment, shown, ready.get(id(fragment)))
            for page in [page for page in self.pages if not ready.keys().isdisjoint(map(id, page.fragments_in_range))]:
                page.range_changed()  # Only a page drawing a changed fragment measures again.
        self.window.check_follow()

    async def toggle_details(self, fragment: TranscriptFragment) -> None:
        """Show a fragment's details, or hide them when they are shown."""
        self.hold_fragment_top(fragment)
        await self._show([(fragment, fragment.shown.toggled())])

    def hold_fragment_top(self, fragment: TranscriptFragment) -> None:
        """Row activation owns the reader: the activated row's top stays visible.

        Activation is the reader's own choice of place; the layout keeps the
        row's top on screen across the rows the toggle adds or removes.
        """
        from toad.widgets.history_anchor import FragmentPosition

        for page in self.pages:
            placed = page.fragment_row(fragment)
            if placed is None:
                continue
            _first, height, drawn = placed
            if drawn:
                self.window.reader_position = FragmentPosition(fragment, 0, height)
            return

    def can_expand(self) -> bool | None:
        fragment = self.block_cursor.current
        return None if fragment is None or not fragment.has_details else not fragment.shown.details_open

    def is_block_expanded(self) -> bool:
        return self.can_expand() is False

    def expand_block(self) -> None:
        self.run_worker(self.toggle_details(self.block_cursor.current), group="message-details")

    def collapse_block(self) -> None:
        self.run_worker(self.toggle_details(self.block_cursor.current), group="message-details")

    # The message cursor

    @property
    def message_row(self) -> MessageRow:
        """The bus message the cursor rests on; its menu is offered on no other fragment."""
        return self.block_cursor.current.row

    @property
    def drawn_fragments(self) -> tuple[TranscriptFragment, ...]:
        """Every fragment the pages draw rows for, oldest first."""
        return tuple(fragment for page in self.pages for fragment in page.drawn_fragments)

    def draws_fragment(self, fragment: TranscriptFragment) -> bool:
        return any(page.fragment_rows(fragment) is not None for page in self.pages)

    def fragment_under_mouse(self, widget: Widget) -> TranscriptFragment | None:
        """The fragment drawn under the pointer, when `widget` is one of this history's pages."""
        return next((page.fragment_under_mouse() for page in self.pages if page is widget), None)

    def fragment_region(self, fragment: TranscriptFragment) -> Region | None:
        """Where the screen shows a fragment's rows; None while its page is off screen."""
        for page in self.pages:
            if (rows := page.fragment_rows(fragment)) is not None:
                if (region := page.screen_region) is None:
                    return None
                return Region(region.x, region.y + rows.start, region.width, len(rows))
        return None

    def fragment_window_rows(self, fragment: TranscriptFragment) -> range | None:
        """The rows of the window's content that draw a fragment.

        Layout places only the pages near the screen. Pages follow one another
        without a gap, so one placed page gives the rows of every other.
        """
        y, rows, shift = 0, None, None
        for page in self.pages:
            if shift is None and (placed := self.window.placed_row(page)) is not None:
                shift = placed - y
            if rows is None and (within := page.fragment_rows(fragment)) is not None:
                rows = range(y + within.start, y + within.stop)
            y += page.line_count
        if rows is None or shift is None:
            return None
        return range(rows.start + shift, rows.stop + shift)

    def show_fragment(self, fragment: TranscriptFragment) -> None:
        """Scroll just far enough that a fragment's rows are on screen, its first row before its last."""
        window = self.window
        if (rows := self.fragment_window_rows(fragment)) is None:
            return
        top, height = int(window.scroll_y), window.scrollable_content_region.height
        if rows.start < top:
            destination = rows.start
        elif rows.stop > top + height:
            destination = min(rows.start, rows.stop - height)
        else:
            return
        window.release_anchor()
        window.scroll_to(y=destination, animate=False, immediate=True)

    @property
    def source_identity(self):
        return self.loader, self.through, self.selected_categories

    def paging_window(self):
        # What an edge check decides from: the saved extent, the pages'
        # loaded ranges and the filter. A check that finds a read running is
        # skipped, and the read asks again only when one of these changed
        # under it, so a filter chosen during a read must count.
        return self.through, self.filter.state, tuple(
            (page.page.before, page.page.after, page.capture_range()) for page in self.pages)

    def capture_reader_ranges(self) -> tuple[PageFragmentRange, ...]:
        """Retain the original source ranges that a returning reader needs."""
        return tuple(page.prepared.capture_range() for page in self.pages)

    def set_reader_ranges(self, ranges) -> None:
        for page in self.pages:
            for page_range in ranges:
                page.prepared.restore_range(page_range)
        if (projection := self.filter.state.overlay) is not None:
            projection.set_reader_ranges(ranges)

    async def restore_reader_ranges(self, ranges, current: Callable[[], bool]) -> bool:
        """A retained native view admits the same source suppliers before paint.

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
                if (page.start == page_range.start and page.stop == page_range.stop
                        and len(page.fragments_in_range) == len(page_range.members)
                        and all(fragment is member for fragment, member in
                                zip(page.fragments_in_range, page_range.members))):
                    continue
                await self.prepare_fragments(page_range.members, current)
                if not await page.select_range(slice(page_range.start, page_range.stop), current):
                    return False
        if (projection := self.filter.state.overlay) is not None:
            if not await projection.restore_reader_ranges(ranges, current):
                return False
        if not current():
            return False
        self._update_edges()
        return True

    def projection_changed(self) -> None:
        self.filter.changed()

    def _require_can_draw(self) -> None:
        if not self.state.can_draw:
            raise _DrawingStopped

    def invalidate_projection(self) -> None:
        self._generation += 1

    def projected_source(self, selected) -> ProjectedTranscriptSource:
        page = self.pages[0]
        return ProjectedTranscriptSource(
            page.prepared,
            self.loader, self.app.preparation, RangeCategoryProjection(
                selected, PageFragmentRange(ref(page.prepared), 0, page.start, page.fragments[:page.start])),

            upstream=self._reader() if self.loader is not None else None,
        )

    @property
    def follows_source_tail(self) -> bool:
        return self.window.follows_tail

    @property
    def has_older(self) -> bool:
        page = self.pages[0]
        return page.prepared.can_extend(True) or page.page.has_older

    @property
    def has_newer(self) -> bool:
        page = self.pages[-1]
        return page.prepared.can_extend(False) or page.page.has_newer

    @property
    def needs_latest_publication(self) -> bool:
        """Whether the newest source is outside the drawn range."""
        return self.has_newer

    @property
    def fragment_limit(self) -> int:
        # Screen rows are not fragment counts: one prepared fragment may contain
        # a dozen lines or a whole indivisible Markdown block. Grow with the
        # number actually visible, keeping two admitted batches in reserve.
        return max(self._fragment_budget, self._visible_fragment_budget())

    def _visible_fragment_budget(self) -> int:
        return self.budget.item_limit(len(self.visible_fragments()))

    @property
    def fragment_count(self) -> int:
        return sum(page.stop - page.start for page in self.pages)

    @property
    def retained_source_bytes(self) -> int:
        return sum(fragment.retained_bytes for fragment in self.fragments_in_range)

    def compose(self) -> ComposeResult:
        yield self.older
        if (projection := self.filter.state.overlay) is not None:
            yield projection
        for page in self.pages:
            page.visible_categories = self.selected_categories
            yield page
        yield self.newer

    async def on_mount(self) -> None:
        await self._finish_mount()

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        """A page joined what this history draws."""

    def extend_source(self, through: TranscriptCursor) -> None:
        """The source now reaches `through`; the drawn pages stay as they are."""
        self._generation += 1
        self.through = through
        edge = self.pages[-1]
        edge.page = replace(edge.page, has_newer=edge.page.after != through)
        self._update_edges()

    async def _finish_mount(self) -> None:
        await self._page_added(self.pages[0].page, self.pages[0].fragments)
        self._update_edges()
        self.observe_source()

    def _update_edges(self) -> None:
        shown = bool(self.selected_categories)
        older, newer = shown and self.filter.older_visible, shown and self.has_newer
        if (older, newer) != (self.older.display, self.newer.display):
            # The edge rows are above and below the reader's.
            self.window.keep_reader()
            self.older.display, self.newer.display = older, newer

    @property
    def conversation(self) -> Conversation | None:
        """The conversation whose live blocks these pages stand in for; None in a saved viewer."""
        from toad.widgets.conversation import Conversation

        return next((ancestor for ancestor in self.ancestors if isinstance(ancestor, Conversation)), None)

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        from toad.widgets.conversation import Contents

        # Root containers own selection; nested pagers already inherit their
        # outer message's category, not the synthetic Markdown fragment role.
        return (self.parent.selected_categories
                if self.is_attached and isinstance(self.parent, Contents) else all_categories())

    @property
    def source_checkpoint_available(self) -> bool:
        return self.filter.checkpoint_available

    def _reader(self) -> PreparedPageSource:
        # The source only grows under one reader; replacing the source clears it (_clear).
        if self._page_buffer is None:
            self._page_buffer = self.page_buffer(self.loader, self.through, self.app.preparation)
        self._page_buffer.through = self.through
        return self._page_buffer

    @property
    def drawn_extent(self) -> tuple[int, int]:
        pages = [page for page in self.pages if page.line_count]
        return sum(page.line_count for page in pages), sum(page.stop - page.start for page in pages)

    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
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

    async def show_newest(self, through, initial: PreparedTranscriptPage) -> None:
        """Replace what is drawn with the newest page of the source as read now."""
        await self._clear(initial)
        self.extend_source(through)
        await self._jump_latest(LatestViewportRequest(LatestPosition.hold(self.window)))

    async def _clear(self, initial: PreparedTranscriptPage) -> None:
        """Forget every drawn page and everything prepared: they belong to another reading."""
        async with self.window.history_lock:
            async with self.window.preserve_history(root=self):
                self._generation += 1
                if self._page_buffer is not None:
                    self._page_buffer.close()
                    self._page_buffer = None
                retired = tuple(self.pages)
                view = TranscriptPageView(initial,
                                          batch_size=self.budget.batch_items)
                view.visible_categories = self.selected_categories
                await self.mount(view, before=self.newer)
                self.pages = deque([view])
                self.through = view.page.after
                self.remove_children(retired)
                self._update_edges()

    async def _load_page(
        self, older: bool, prepared: PreparedTranscriptPage | None = None,
        publication_current: Callable[[], bool] = lambda: True,
    ) -> bool:
        """Publish one readable range; report whether its edge still needs rows."""
        snapshot = self.source_snapshot()
        window, loader = snapshot.window, self.loader
        # Only an append beyond the fully drawn, followed end is an arrival.
        # Local range growth, older paging and destination restoration are not.
        fresh = not older and not self.has_newer and self.follows_source_tail

        def current() -> bool:
            if not snapshot.current(self) or not publication_current():
                return False
            return (window.follows_tail if fresh
                    else window.lookahead.demand.accepts_result(older))

        try:
            if not current():
                return False
            edge = self.pages[0] if older else self.pages[-1]
            page_range = edge.capture_range()
            edge_cursor = edge.page.before, edge.page.after
            demand = window.lookahead.demand
            missing = (window.lookahead.ahead_rows(window.outer_size.height) if fresh
                       else window.lookahead.read_rows(self, older))
            local = edge.prepared.can_extend(older)
            staged = edge.prepared.for_view() if local else prepared
            if not local:
                if loader is None:
                    return False
                if staged is None:
                    staged = await self._reader().get(PageRequest.adjacent(edge.page, older))
                    demand.source_read()
            # Speculation warms the same scoped runtime entry as the next
            # foreground request; it does not copy decoded pages into a widget.
            window.lookahead.demand.prepare_ahead(window.lookahead, self, staged.page, older)
            boundary = (edge.start if older else edge.stop) if local else (len(staged.fragments) if older else 0)
            await staged.prepare_rows(
                self, current, target=self, selected=self.selected_categories,
                boundary=boundary, older=older,
                rows_needed=max(1, missing),
                limit=self.fragment_limit,
            )
            if not current():
                return False
            async with window.history_lock:
                if not current():
                    return False
                if (self.pages[0] if older else self.pages[-1]) is not edge:
                    return False
                if edge.capture_range() != page_range:
                    return False
                protected = {id(fragment) for fragment in self.visible_fragments()}
                async with window.preserve_history(root=self):
                    await self._extend_and_trim(edge, older, local, protected, staged, current=current,
                                                fresh=fresh and self._source_state.rows_arrive)
                    self._require_can_draw()
                    self._source_state.rows_published(self)
            self.state.delivered(self)
            advanced = self.pages[0] if older else self.pages[-1]
            if (advanced is edge and edge.capture_range() == page_range
                    and (edge.page.before, edge.page.after) == edge_cursor):
                return False
            if fresh or not current():
                return False
            return bool(window.lookahead.read_rows(self, older))
        except _DrawingStopped:
            return False
        finally:
            if self.state.can_draw:
                self.window.check_follow()

    async def _extend_and_trim(
        self, edge: TranscriptPageView, older: bool, local: bool,
        protected: set[int], prepared: PreparedTranscriptPage, *,
        current: Callable[[], bool], fresh: bool = False,
    ) -> None:
        """Admit the next range and trim fragments the reader is not seeing.

        protected holds ids of fragments that must stay admitted: the visible
        ones and those just admitted for the reader's direction of travel.
        """
        async with self.lock:
            previous_start = self.pages[0], self.pages[0].start
            overlay_visible = self.filter.projection_visible()
            protected_pages: set[TranscriptPageView] = set()
            if not prepared.fragments:
                # A nonmatching interval advances the original source span,
                # not the native tree. No empty page widget or decoded cache.
                edge.prepared.advance_empty(prepared, older)
                await self._page_added(prepared.page, prepared.fragments)
            elif local:
                previous = {id(fragment) for fragment in edge.fragments_in_range}
                if not await edge.prepared.extend(edge, prepared, current):
                    raise _DrawingStopped
                self._require_can_draw()
                protected.update(id(fragment) for fragment in edge.fragments_in_range
                                 if id(fragment) not in previous)
            else:
                page_range = edge.capture_range()
                async with TranscriptPageView.acquire(
                    self, prepared, fresh=fresh, before=edge if older else self.newer,
                    current=lambda: current() and edge.capture_range() == page_range,
                ) as view:
                    if older:
                        self.pages.appendleft(view)
                    else:
                        self.pages.append(view)
                protected.update(id(fragment) for fragment in view.fragments_in_range)
                protected_pages.add(view)
                await self._page_added(prepared.page, prepared.fragments)
            self._fragment_budget = limit = max(
                self.budget.item_limit(len(protected)), self._visible_fragment_budget(),
            )
            excess = self.fragment_count - limit
            trim_older = self.follows_source_tail or not older
            while (excess > 0 or len(self.pages) > limit) and (self.fragment_count > 1 or len(self.pages) > 1):
                selected = None
                for side in (trim_older, not trim_older):
                    # A visible older projection protects the range between it
                    # and the canonical pages, just like a visible page.
                    if side and overlay_visible:
                        continue
                    candidate = self.pages[0] if side else self.pages[-1]
                    if candidate in protected_pages:
                        continue
                    members = list(candidate.fragments_in_range)
                    if not side:
                        members.reverse()
                    available = 0
                    for fragment in members:
                        if id(fragment) in protected:
                            break
                        available += 1
                    if available or not members:
                        selected = candidate, side, available
                        break
                if selected is None:
                    break
                evicted, side, available = selected
                count = evicted.stop - evicted.start
                remove_count = min(max(0, excess), available, self.fragment_count - 1)
                if remove_count >= count and len(self.pages) > 1:
                    self.pages.popleft() if side else self.pages.pop()
                    evicted.remove()
                    excess -= count
                else:
                    if not remove_count:
                        break
                    evicted.prepared.trim(evicted, min(remove_count, count), older=side)
                    excess -= remove_count
            self.filter.canonical_moved(previous_start, overlay_visible)
            self._update_edges()

class TranscriptHistory(CommittedHistory, LineHistory):
    """The line history of a saved transcript.

    Its pages stand in for the conversation's live blocks: it reports which
    events it covers, follows the committed end of the transcript, and can be
    parked with a tab and rebuilt from what was parked.
    """

    def notification_read(self, references) -> ReadNotifications:
        from toad.widgets.conversation import Conversation

        scope = self.query_ancestor(Conversation).transcript.thread_scope
        if scope is None:
            raise ValueError("Notification observation requires a bound thread")
        return ReadNotifications(scope[0], references)

    def __init__(self, prepared: PreparedTranscriptPage, loader: Callable[..., Awaitable[TranscriptPage]] | None = None,
                 *, committed: bool = True, **kwargs):
        super().__init__(prepared, loader, **kwargs,
                         source_state=LiveTranscript() if committed else ProvisionalTranscript())

class ProjectedTranscriptHistory(TranscriptHistory):
    """A source projection with the ordinary pager's admission and eviction policy."""

    def notification_read(self, references) -> ReadNotifications:
        return self._projection_owner().notification_read(references)

    def __init__(self, owner: TranscriptHistory, source: ProjectedTranscriptSource,
                 prepared: PreparedTranscriptPage) -> None:
        self._projection_owner = ref(owner)
        super().__init__(prepared, source.loader, budget=owner.budget)
        self._page_buffer = source
        self.add_class("filtered-history-results")

    @classmethod
    def from_source(cls, source: ProjectedTranscriptSource, *, owner: TranscriptHistory):
        if not source.held_pages or source.closed:
            raise ValueError("No retained projected admission")
        history = cls(owner, source, source.held_pages[0])
        history.pages.extend(TranscriptPageView(
            page, batch_size=owner.budget.batch_items,
        ) for page in source.held_pages[1:])
        history._source_state = ParkedSourceTranscript(LiveTranscript())
        return history

    @property
    def older_page_available(self) -> bool:
        return self.checkpoint_available and self.has_older

    def request_older(self) -> None:
        if self.older_page_available:
            self.request_page(True)

    async def load_older(self) -> None:
        if self.older_page_available:
            await self.reserve_source_work().execute(self, partial(self._prepare_edge, True))

    @property
    def state(self) -> TranscriptState:
        return super().state.for_projection(self, self._projection_owner())

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        # Selection was applied by the source; the view never reinterprets it.
        return all_categories()

    @property
    def follows_source_tail(self) -> bool:
        # This window is a historical prefix, not the live canonical tail.
        return False

    def _reader(self) -> PreparedPageSource:
        assert self._page_buffer is not None
        return self._page_buffer

    @property
    def coverage_events(self) -> Iterator[TranscriptEvent]:
        return (event for page in self.pages for fragment in page.fragments for event in fragment.events)

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        owner = self._projection_owner()
        if owner is not None and owner.filter.owns_projection(self):
            await owner._page_added(replace(page, events=tuple(
                event for fragment in fragments for event in fragment.events
            )), fragments)
