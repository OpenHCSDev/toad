"""Bounded, cursor-paged saved history; all transcript interpretation is model-owned."""

from __future__ import annotations
from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import OtherCategory

import asyncio
from bisect import bisect_right
from collections import deque
from contextlib import ExitStack, asynccontextmanager
from dataclasses import replace
from functools import partial
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import TYPE_CHECKING
from weakref import ref

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent, ContextTranscript, UserTranscript, IncomingTranscript, AgentTextTranscript, SentTranscript,
    ThinkingTranscript,
)
from textual import events, on
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.message import Message
from textual.widget import Widget
from textual.walk import walk_depth_first
from textual.strip import Strip
from textual.widgets import Static

from toad.transcript_filter import TranscriptFilter
from toad.transcript_state import TranscriptState, LiveTranscript, ProvisionalTranscript, ParkedSourceTranscript, LatestViewportRequest
from toad.transcript_source_preparation import TranscriptSourcePreparation
from toad.transcript_preparation import (
    CategoryProjection, PageRequest, PreparedPageSource, PreparedTranscriptPage, TranscriptPageAdmission, TranscriptPageBuffer,
    ProjectedTranscriptSource,
)
from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from toad.widgets.message_divider import AgentActivityDivider, MessageClock
from toad.widgets.presentation_window import PresentationBudget
from toad.widgets.transcript_lines import LineTheme, PreparedLines, TranscriptLinesRenderTask
from toad.widgets.committed_presentation import CommittedHistory, TranscriptInputClaim
from toad.core.source_events import TranscriptCoverage
from toad.widgets.message_filter import (
    all_categories, CategorizedBlock, MessageCategory, apply_block_filter, event_category, keep_events,
)
from toad.widgets.transcript_fragments import (
    TranscriptFragment, transcript_fragments,
)

if TYPE_CHECKING:
    from toad.widgets.history_anchor import HistoryWindow

class _PublicationRetired(Exception):
    """Unwind an anchor transaction whose source owner no longer publishes."""

class HistoryEdge(Static, can_focus=True):
    DEFAULT_CSS = "HistoryEdge { height: 1; color: $text-muted; pointer: pointer; }"
    BINDINGS = [("enter,space", "earlier", "Earlier history")]

    class Requested(Message):
        pass

    def action_earlier(self) -> None:
        self.post_message(self.Requested())

    def on_click(self, event) -> None:
        if event.button == 1:
            event.stop()
            self.action_earlier()

class JumpToLatest(Static, can_focus=True):
    BINDINGS = [("enter,space", "jump", "Jump to latest")]
    DEFAULT_CSS = "JumpToLatest { height: 1; color: $text-secondary; pointer: pointer; }"

    class Requested(Message):
        pass

    def action_jump(self) -> None:
        self.post_message(self.Requested())

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.action_jump()

class TranscriptPageView(Widget):
    """One transcript page, drawn as its admitted fragments' prepared lines.

    Fragments never become widgets. Styled rows come from the render worker
    processes; until they arrive a fragment draws its plain wrapped text.
    """

    DEFAULT_CSS = "TranscriptPageView { height: auto; }"
    RENDER_BATCH = 8

    def __init__(self, page: TranscriptPage, *, newest: bool = True,
                 fragments: tuple[TranscriptFragment, ...] | None = None,
                 batch_size: int = PreparedTranscriptPage.BATCH,
                 prepared: PreparedTranscriptPage | None = None):
        self.prepared = prepared if prepared is not None else PreparedTranscriptPage(
            page, transcript_fragments(page.events) if fragments is None else
            tuple(fragments), 0,
        )
        self.visible_categories = all_categories()
        self.prepared.configure(batch_size=batch_size, newest=newest)
        self._theme: LineTheme | None = None
        self._pending: set[int] = set()
        self._render: asyncio.Task[None] | None = None
        self._width = 0
        self._layout: list[tuple[int, int, tuple[Strip, ...]]] = []
        self._starts: list[int] = []
        self._height = 0
        super().__init__()

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
    def batch_size(self):
        return self.prepared.batch_size

    @batch_size.setter
    def batch_size(self, size):
        self.prepared.batch_size = size

    @property
    def admitted_fragments(self) -> tuple[TranscriptFragment, ...]:
        return self.fragments[self.start:self.stop]

    @property
    def line_width(self) -> int:
        """The width this page last laid out at; reading it never forces layout."""
        return self._width

    @property
    def line_count(self) -> int:
        return self._height

    def on_mount(self) -> None:
        self.watch(self.app, "theme", self._theme_changed, init=False)

    def _theme_changed(self) -> None:
        # Lines hold resolved theme colors; a new theme draws new lines.
        self._theme = None
        self.admission_changed()

    def on_unmount(self) -> None:
        if self._render is not None:
            self._render.cancel()

    def admission_changed(self) -> None:
        """The prepared range moved; draw the new range's rows."""
        self._relayout()
        self.refresh(layout=True)

    def _line_theme(self) -> LineTheme:
        if self._theme is None:
            self._theme = LineTheme.from_app(self.app)
        return self._theme

    def _rows(self, index: int, width: int) -> tuple[Strip, ...]:
        fragment, theme = self.fragments[index], self._line_theme()
        lines = fragment.lines_for(width, theme)
        if lines is None:
            self._pending.add(index)
            lines = fragment.plain_lines(width, theme)
        return lines.strips

    def _relayout(self, width: int | None = None) -> None:
        width = self._width if width is None else width
        self._width = width
        layout, starts, y = [], [], 0
        if width > 0:
            for index in range(self.start, self.stop):
                fragment = self.fragments[index]
                if not keep_events(fragment.events, self.visible_categories):
                    continue
                rows = self._rows(index, width)
                layout.append((index, y, rows))
                starts.append(y)
                y += len(rows)
        self._layout, self._starts, self._height = layout, starts, y
        if self._pending and self.is_attached and (self._render is None or self._render.done()):
            self._render = asyncio.create_task(self._render_pending())

    def get_content_height(self, container, viewport, width: int) -> int:
        if width != self._width:
            self._relayout(width)
        return self._height

    def render_line(self, y: int) -> Strip:
        # Layout supplies the width through get_content_height; reading size
        # here would look this widget up in the compositor for every row.
        width = self._width
        slot = bisect_right(self._starts, y) - 1
        if slot < 0:
            return Strip.blank(width)
        _index, first, rows = self._layout[slot]
        row = y - first
        strip = rows[row] if row < len(rows) else Strip.blank(width)
        return strip.extend_cell_length(width).crop(0, width)

    def fragment_line(self, fragment: TranscriptFragment) -> int | None:
        """The first row of an admitted fragment within this page."""
        for index, first, _rows in self._layout:
            if self.fragments[index] is fragment:
                return first
        return None

    def fragment_at(self, row: int) -> tuple[TranscriptFragment, int] | None:
        """The admitted fragment drawn at a row of this page, and the row within it."""
        slot = bisect_right(self._starts, row) - 1
        if slot < 0:
            return None
        index, first, _rows = self._layout[slot]
        return self.fragments[index], row - first

    def visible_fragments(self, window) -> tuple[TranscriptFragment, ...]:
        """Admitted fragments overlapping the window's viewport."""
        from toad.widgets.history_anchor import HistoryAnchor

        offset = HistoryAnchor._offset(self, window)
        top = window.scroll_y - offset
        bottom = top + window.outer_size.height
        return tuple(self.fragments[index] for index, first, rows in self._layout
                     if first < bottom and first + len(rows) > top)

    def _nearest_pending(self) -> list[int]:
        from toad.widgets.history_anchor import HistoryAnchor, HistoryWindow

        window = self.query_ancestor(HistoryWindow)
        reader = window.scroll_y - HistoryAnchor._offset(self, window)
        rows = {index: first for index, first, _rows in self._layout}
        admitted = [index for index in self._pending if index in rows]
        self._pending.difference_update(set(self._pending) - set(admitted))
        admitted.sort(key=lambda index: abs(rows[index] - reader))
        return admitted[:self.RENDER_BATCH]

    async def _render_pending(self) -> None:
        renderer = self.app.render_processes
        while self._pending and self.is_attached:
            batch = self._nearest_pending()
            if not batch:
                return
            self._pending.difference_update(batch)
            width, theme = self._width, self._line_theme()
            results = await asyncio.gather(*(
                renderer.submit(TranscriptLinesRenderTask(
                    self.fragments[index].line_blocks(show_divider=not self.fragments[index].continuation),
                    width, theme))
                for index in batch), return_exceptions=True)
            if not self.is_attached or width != self._width:
                continue
            ready = [(index, result) for index, result in zip(batch, results)
                     if isinstance(result, PreparedLines)]
            if ready:
                await self._publish(ready)

    async def _publish(self, ready: list[tuple[int, PreparedLines]]) -> None:
        from toad.widgets.history_anchor import HistoryWindow

        window = self.query_ancestor(HistoryWindow)
        history = self.query_ancestor(TranscriptHistory)
        async with window.preserve_history(None, root=self, position=history.reader_position(window)):
            theme = self._line_theme()
            for index, lines in ready:
                self.fragments[index].hold_lines(theme, lines)
            self.admission_changed()

    def retain_sources(self) -> None:
        """Pages hold immutable fragments; nothing native to transfer."""
        self.prepared.retain_sources(self)
        self.prepared.retained_bytes = 0

    @classmethod
    @asynccontextmanager
    async def acquire(
        cls, owner: TranscriptHistory, page: TranscriptPage, *, fragments,
        batch_size: int, before: Widget, current: Callable[[], bool], newest: bool = True,
        prepared: PreparedTranscriptPage | None = None,
    ) -> AsyncIterator[TranscriptPageView]:
        """Acquire a page until its original source transfers native custody."""
        view = cls(page, fragments=fragments, prepared=prepared, batch_size=batch_size, newest=newest)
        view.prepared.select_admission(PreparedTranscriptPage.initial_slice(view.fragments, batch_size, newest))
        view.prepared.retain_sources(view)
        view.visible_categories = owner.selected_categories
        with ExitStack() as acquisition:
            acquisition.callback(owner.remove_children, (view,))
            await owner.mount(view, before=before)
            if not current():
                raise _PublicationRetired
            yield view
            acquisition.pop_all()

    def capture_admission(self) -> TranscriptPageAdmission:
        return self.prepared.capture_admission()

    def set_categories(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.visible_categories = selected
        self.admission_changed()

    async def prepare_adjacent(self, preparation, demand, count: int, keep_going) -> None:
        """Warm unadmitted fragments beside this page's admission."""
        await preparation.prepare_fragments(
            demand.neighbors(self.fragments, self.start, self.stop, count), keep_going,
        )

    async def select_range(
        self, selected: slice, current: Callable[[], bool],
        *, suppliers: tuple[TranscriptFragment, ...] | None = None,
    ) -> bool:
        if not current():
            return False
        window = self.query_ancestor(TranscriptHistory).window
        async with window.history_lock:
            if not current():
                return False
            history = self.query_ancestor(TranscriptHistory)
            async with window.preserve_history(None, root=self, position=history.reader_position(window)):
                return await self.prepared.replace_range(self, self.fragments, selected, None, current)


class TranscriptHistory(TranscriptSourcePreparation, ConversationBlock, CommittedHistory, CategorizedBlock, VerticalGroup):
    CACHE_SUBTREE_GEOMETRY = True
    MAX_FRAGMENTS = 240

    @property
    def message_category(self) -> None:
        return None

    def __init__(self, page: TranscriptPage, loader: Callable[..., Awaitable[TranscriptPage]] | None = None,
                  *, fragments: tuple[TranscriptFragment, ...] | None = None,
                  budget: PresentationBudget | None = None, committed: bool = True,
                  prepared: PreparedTranscriptPage | None = None):
        super().__init__(source_state=LiveTranscript() if committed else ProvisionalTranscript())
        self.loader, self.through = loader, page.after
        self.budget = budget or PresentationBudget(
            max_items=self.MAX_FRAGMENTS, admission_items=PreparedTranscriptPage.BATCH,
        )
        self.pages = deque([TranscriptPageView(
            page, fragments=fragments, prepared=prepared, batch_size=self.budget.admission_items,
        )])
        self.older = HistoryEdge("↑ Earlier history loads as you scroll")
        self.older.tooltip = "Click or press Enter to load earlier history, including in In/out only mode"
        self.newer = JumpToLatest("↓ Jump to latest")
        self.filter = TranscriptFilter(self)
        self._fragment_budget = self.budget.max_items
        self.window: HistoryWindow

    async def park_document(self) -> PreparedPageSource:
        """Transfer original data and admission out of disposable native pages."""
        await self.retire_source(parked=True)
        source = self._reader()
        projection = self.filter.state.overlay
        projected = await projection.park_document() if projection is not None else None
        for page in self.pages:
            page.retain_sources()
        pages = tuple(page.prepared for page in self.pages)
        position = self.window.pending_reader_position
        await source.runtime.run_thread(source.measure_admission, pages, projected,
                                        () if position is None else position.admissions)
        source.park(pages, projected)
        return source

    @classmethod
    def from_source(cls, source: PreparedPageSource) -> TranscriptHistory:
        """Reacquire the original pages; retained source is not live coverage."""
        pages = source.admitted
        if not pages or source.closed:
            raise ValueError("No retained transcript admission")
        history = cls(pages[0].page, source.loader, prepared=pages[0])
        history.through = source.through
        history._page_buffer = source
        history._source_state = ParkedSourceTranscript(LiveTranscript())
        history.pages.extend(TranscriptPageView(
            page.page, prepared=page, batch_size=history.budget.admission_items,
        ) for page in pages[1:])
        projected = source.projection_source
        if projected is not None:
            from toad.transcript_filter import Filtered
            projection = ProjectedTranscriptHistory.from_source(projected, owner=history)
            history.filter.state = Filtered(projection)
        return history

    def acquire_document(self) -> None:
        """Mounted consumers have taken custody of the same data resources."""
        if self._page_buffer is not None:
            self._page_buffer.release_admission()
        if (projection := self.filter.state.overlay) is not None:
            projection.acquire_document()

    def resume_source(self) -> None:
        super().resume_source()
        if (projection := self.filter.state.overlay) is not None:
            projection.resume_source()

    async def prepare_fragments(self, fragments, current: Callable[[], bool], *, selected=None) -> None:
        """Render fragments' lines at the page width before they are admitted."""
        width = self.line_width
        if width <= 0:
            return
        theme = LineTheme.from_app(self.app)
        selected = self.selected_categories if selected is None else selected
        todo = [fragment for fragment in fragments
                if keep_events(fragment.events, selected) and fragment.lines_for(width, theme) is None]
        renderer = self.app.render_processes
        for first in range(0, len(todo), self.budget.admission_items):
            if not current():
                return
            batch = todo[first:first + self.budget.admission_items]
            results = await asyncio.gather(*(
                renderer.submit(TranscriptLinesRenderTask(
                    fragment.line_blocks(show_divider=not fragment.continuation), width, theme))
                for fragment in batch), return_exceptions=True)
            for fragment, result in zip(batch, results):
                if isinstance(result, PreparedLines):
                    fragment.hold_lines(theme, result)

    @property
    def line_width(self) -> int:
        """The width pages draw at, as laid out; 0 before the first layout."""
        return next((page.line_width for page in self.pages if page.line_width), 0)

    async def prepare_body(self, current: Callable[[], bool], *, selected=None) -> None:
        """Warm the actual page admissions, including a restored reader range."""
        if (projection := self.filter.state.overlay) is not None:
            await projection.prepare_body(current)
        for page in self.pages:
            await self.prepare_fragments(page.admitted_fragments,
                                         current, selected=selected)

    @property
    def admitted_fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.admitted_fragments)

    def visible_fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.visible_fragments(self.window))

    def reader_position(self, window):
        """The reader's row as a position that survives rows changing above it."""
        from toad.widgets.history_anchor import HistoryAnchor, LineAnchor

        if window.follows_tail:
            return HistoryAnchor.capture(self.newer, window)
        for page in self.pages:
            offset = HistoryAnchor._offset(page, window)
            row = int(window.scroll_y - offset)
            if row < 0:
                return HistoryAnchor.capture(self.older, window)
            if row < page.line_count and (found := page.fragment_at(row)) is not None:
                fragment, _within = found
                return LineAnchor(page, window.scroll_y, window.scroll_revision,
                                  fragment=fragment, virtual_y=offset + page.fragment_line(fragment))
        return HistoryAnchor.capture(self.newer, window)

    @property
    def source_identity(self):
        return self.loader, self.through, self.selected_categories

    def paging_window(self):
        # Source progress observes admission; only an actual reader capture
        # takes custody of the native producers' resolved acquisitions.
        return self.through, tuple(page.capture_admission() for page in self.pages)

    def report_source_coverage(self) -> None:
        if self._source_state.reports_coverage:
            self.publish_core(TranscriptCoverage(tuple(self.coverage_events)))

    def capture_reader_admissions(self) -> tuple[TranscriptPageAdmission, ...]:
        """Retain the original source ranges that a returning reader needs."""
        for page in self.pages:
            page.retain_sources()
        return tuple(page.prepared.capture_admission() for page in self.pages)

    def restore_reader_admissions(self, admissions) -> None:
        for page in self.pages:
            for admission in admissions:
                page.prepared.restore_admission(admission)
        if (projection := self.filter.state.overlay) is not None:
            projection.restore_reader_admissions(admissions)

    async def restore_reader_ranges(self, admissions, current: Callable[[], bool]) -> bool:
        """A retained native view admits the same source suppliers before paint.

        Parked reconstruction sets source demand before composition. A live
        page still has its preceding children, so it uses the original range
        transaction to join new membership before evaluating reader placement.
        """
        for page in self.pages:
            for admission in admissions:
                if admission.page() is not page.prepared:
                    continue
                if not current():
                    return False
                if (page.start == admission.start and page.stop == admission.stop
                        and len(page.admitted_fragments) == len(admission.members)
                        and all(fragment is member for fragment, member in
                                zip(page.admitted_fragments, admission.members))):
                    continue
                await self.prepare_fragments(admission.members, current)
                if not await page.select_range(slice(admission.start, admission.stop), current,
                                               suppliers=admission.members):
                    return False
        if (projection := self.filter.state.overlay) is not None:
            if not await projection.restore_reader_ranges(admissions, current):
                return False
        if not current():
            return False
        self._update_edges()
        return True

    def projection_changed(self) -> None:
        self.filter.changed()

    def _require_publication(self) -> None:
        if not self.state.accepts_publication:
            raise _PublicationRetired

    def invalidate_projection(self) -> None:
        self._generation += 1

    def projected_source(self, selected) -> ProjectedTranscriptSource:
        page = self.pages[0]
        return ProjectedTranscriptSource(
            PreparedTranscriptPage(page.page, page.fragments[:page.start], 0),
            self.loader, self.app.preparation, CategoryProjection(selected),
            upstream=self._reader() if self.loader is not None else None,
        )

    @property
    def _follow_source_tail(self) -> bool:
        return self.window.follows_tail

    async def _report_coverage(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        if self._source_state.reports_coverage:
            from toad.widgets.conversation import Conversation
            # Transfer covered native display inside the page admission. The
            # original retirement receipt owns teardown; observe its completed
            # result without holding the Conversation pump or mount admission.
            # Standalone saved viewers have no live transcript to transfer.
            # Resolve custody from native ancestry, not a second owner field.
            for ancestor in self.ancestors:
                if isinstance(ancestor, Conversation):
                    ancestor.transcript.covered(TranscriptCoverage(page.events), self).call_when_ready(ancestor)
                    break

    def publish_committed(self) -> None:
        """Acquire live-row ownership only after a provisional mount is accepted."""
        self._source_state = self._source_state.publish()
        self.publish_core(TranscriptCoverage(tuple(self.coverage_events)))
        self.request_preparation()

    @property
    def coverage_events(self) -> Iterator[TranscriptEvent]:
        return (event for page in self.pages for event in page.page.events)

    @property
    def has_older(self) -> bool:
        page = self.pages[0]
        return page.start > 0 or page.page.has_older

    @property
    def has_newer(self) -> bool:
        page = self.pages[-1]
        return page.stop < len(page.fragments) or page.page.has_newer

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
        return sum(fragment.retained_bytes for fragment in self.admitted_fragments)

    def compose(self) -> ComposeResult:
        yield self.older
        if (projection := self.filter.state.overlay) is not None:
            yield projection
        for page in self.pages:
            page.visible_categories = self.selected_categories
            yield page
        yield self.newer

    async def on_mount(self) -> None:
        from toad.widgets.history_anchor import HistoryWindow
        self.window = self.query_ancestor(HistoryWindow)
        await self._finish_mount()

    async def _finish_mount(self) -> None:
        await self._report_coverage(self.pages[0].page, self.pages[0].fragments)
        self._update_edges()
        self.observe_source()

    def _update_edges(self) -> None:
        if not self.selected_categories:
            self.older.display = self.newer.display = False
            return
        self.older.display = self.filter.older_visible
        self.newer.display = self.has_newer

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        from toad.widgets.conversation import Contents, Conversation

        # A nested pager inherits the outer message's category, not the
        # synthetic role of its Markdown fragments.
        return (self.query_ancestor(Conversation).visible_categories
                if self.is_attached and isinstance(self.parent, Contents) else all_categories())

    def covers_incoming(self, sequence: int) -> bool:
        if not self._source_state.reports_coverage:
            return False
        if self.committed_cursor.covers_incoming(sequence):
            return True
        if sequence in TranscriptCoverage(tuple(self.coverage_events)).sequences:
            return True
        return self.filter.covers_incoming(sequence)

    @property
    def committed_cursor(self) -> TranscriptCursor:
        return self.through

    @property
    def source_checkpoint_available(self) -> bool:
        return self.filter.checkpoint_available

    def retain_committed(self, through: TranscriptCursor) -> None:
        """Extend access to saved source without moving the displayed page window."""
        if not self.accepts_commit(through):
            raise ValueError("Commit replaces or rewinds the retained source")
        self._generation += 1
        self.through = through
        edge = self.pages[-1]
        edge.page = replace(edge.page, has_newer=edge.page.after != through)
        self._update_edges()

    async def advance_committed(
        self, through: TranscriptCursor, is_current: Callable[[], bool],
    ) -> bool:
        """Advance in bounded native pages and render batches, preserving loaded rows."""
        async with self.window.history_lock:
            if not self.checkpoint_available or not is_current():
                return False
            # Reject scans started with the old bound without discarding their
            # already accepted filtered overlay or its backward cursor.
            self.retain_committed(through)
            operation = self.reserve_source_work()
        return await operation.execute(self, partial(self._advance_committed, is_current))

    async def _advance_committed(self, is_current: Callable[[], bool]) -> bool:
        while self.has_newer:
            if not is_current() or not self.state.accepts_publication:
                return False
            edge = self.pages[-1]
            previous = edge.page.after, edge.stop
            await self._load_page(False)
            edge = self.pages[-1]
            if previous == (edge.page.after, edge.stop):
                return False
            # Let the bounded batch paint before selecting the next batch's
            # visible anchors. Never mount an entire oversized native row.
            refreshed = asyncio.get_running_loop().create_future()
            self.call_after_refresh(
                lambda future=refreshed: future.done() or future.set_result(None)
            )
            await refreshed
        return is_current()

    def _reader(self) -> PreparedPageSource:
        reader = self._page_buffer
        if reader is None or reader.loader is not self.loader or reader.through != self.through:
            if reader is not None:
                reader.close()
            self._page_buffer = reader = TranscriptPageBuffer(
                self.loader, self.through, self.app.preparation,
            )
            self._prefetch_intent = None
        return reader

    def prepare_scroll(self) -> None:
        if (self.loader is None or not self.is_mounted or not self.state.accepts_publication or not self.screen.is_current
                or not self.selected_categories):
            return
        reader = self._reader()
        edges = (self.pages[0].page.before if self.pages[0].page.has_older else None,
                 self.pages[-1].page.after if self.pages[-1].page.has_newer else None)
        lookahead = self.window.lookahead
        demand = lookahead.demand
        edges = demand.edges(*edges)
        rows = max(1, self.window.outer_size.height)
        pages = tuple(dict.fromkeys((self.pages[0], self.pages[-1])))
        count = lookahead.preparation_count(rows)
        # Source pages and terminal viewports are different units. Borrow the
        # original pages' actual fragment extent; the reader/runtime bounds
        # transport rounds and storage independently of native admission.
        fragments_per_page = max(1, min(len(page.fragments) for page in pages))
        rounds = max(1, (count + fragments_per_page - 1) // fragments_per_page)
        admissions = tuple(page.capture_admission() for page in pages)
        self.request_lookahead((reader, edges, rounds, count, demand, pages, admissions,
                                self.source_snapshot()))

    async def prepare_lookahead(self, intent) -> None:
        reader, edges, rounds, count, demand, pages, admissions, snapshot = intent
        current = partial(self.lookahead_current, intent)
        for page in pages:
            await page.prepare_adjacent(self, demand, count, current)
        async for prepared in reader.prefetch(*edges, current, rounds=rounds):
            await self.prepare_fragments(
                demand.neighbors(prepared.fragments, len(prepared.fragments), 0, count), current,
            )

    def lookahead_current(self, intent) -> bool:
        reader, _edges, _rounds, _count, demand, pages, admissions, snapshot = intent
        return (snapshot.current(self)
                and snapshot.window.lookahead.accepts(demand)
                and all(page.capture_admission() == admission
                        for page, admission in zip(pages, admissions)))

    def _check_edges(self) -> None:
        if (not self.checkpoint_available
                or not self.screen.is_active or not self.selected_categories):
            return
        # Off-screen pagers must not ask for their region: after a scroll that
        # falls back to rebuilding geometry for the *whole* mounted transcript.
        # The layout signal also calls us once this pager enters the viewport.
        geometry = self.screen._compositor.visible_widgets.get(self)
        if geometry is None:
            return
        region, _clip = geometry
        window = self.screen._compositor.visible_widgets.get(self.window)
        if window is None:
            return
        viewport = window[0]
        if not region.overlaps(viewport):
            return
        # Original published geometry admits source work, even while a body is
        # preparing. Its worker owns read/prepare/native mutation; the existing
        # viewport frame owner alone decides when those bodies may be painted.
        if self._follow_source_tail and self.has_newer:
            self._request_page(False)
            return
        if self.filter.active:
            self.filter.check_edges()
            return
        if (self.has_older and region.y >= viewport.y - self.prefetch_distance
               and not (self._follow_source_tail and (
                    self.fragment_count >= self.fragment_limit or len(self.pages) >= self.fragment_limit
              ))):
            self._request_page(True)
        elif self.has_newer and region.bottom <= viewport.bottom + self.prefetch_distance:
            self._request_page(False)

    @on(JumpToLatest.Requested)
    def on_jump(self, event: JumpToLatest.Requested) -> None:
        event.stop()
        self.window.jump_to_latest()

    @on(HistoryEdge.Requested)
    def on_earlier_history(self, event: HistoryEdge.Requested) -> None:
        event.stop()
        if self.filter.active:
            self.filter.request_older()
        elif self.has_older and self.state.accepts_source_work:
            self._request_page(True)

    async def _publish_latest(self, request: LatestViewportRequest) -> bool:
        snapshot = self.source_snapshot()
        window, loader = snapshot.window, self.loader
        destination_admission = window.lookahead.admission(self.budget, window.outer_size.height)
        view = self.pages[-1]
        if loader is None or view.page.after == self.through:
            # The original source already supplies the newest cut. End moves
            # its native demand; another read cannot improve its coverage.
            prepared = view.prepared
        else:
            prepared = await self._reader().get(PageRequest(before=self.through))
        page, fragments = prepared.page, prepared.fragments
        selected = PreparedTranscriptPage.initial_slice(fragments, destination_admission, True)
        await self.prepare_fragments(
            fragments[selected],
            lambda: snapshot.current(self) and request.current(window),
        )
        async with window.history_lock:
            if not snapshot.current(self) or not request.current(window):
                return False
            if self.pages[-1] is not view:
                return False
        if prepared is view.prepared:
            # End changes the original admission, without locking the window
            # around pending body writers or replacing their paint resources.
            view.batch_size = destination_admission
            if not await view.select_range(
                selected, lambda: snapshot.current(self) and request.current(window),
            ):
                return False
        async with window.history_lock:
            if not snapshot.current(self) or not request.current(window):
                return False
            async with window.preserve_history(None, root=self):
                previous = tuple(self.pages)
                if prepared is view.prepared:
                    self.pages = deque([view])
                else:
                    try:
                        async with TranscriptPageView.acquire(
                            self, page, fragments=fragments, batch_size=destination_admission,
                            prepared=prepared,
                            before=self.newer, current=lambda: snapshot.current(self) and request.current(window),
                        ) as view:
                            self.pages = deque([view])
                    except _PublicationRetired:
                        return False
                self.remove_children(tuple(retired for retired in previous if retired is not view))
                self._update_edges()
            return True

    async def _load_page(self, older: bool) -> None:
        snapshot = self.source_snapshot()
        window, loader = snapshot.window, self.loader
        edge = self.pages[0] if older else self.pages[-1]
        admission = edge.capture_admission()
        try:
            local = edge.start > 0 if older else edge.stop < len(edge.fragments)
            page = None
            fragments = None
            prepared = None
            if not local:
                if loader is None:
                    return
                prepared = await self._reader().get(PageRequest(
                    before=edge.page.before if older else None,
                    after=edge.page.after if not older else None,
                ))
                page, fragments = prepared.page, prepared.fragments
            selected = (edge.prepared.extension_slice(older) if local
                        else PreparedTranscriptPage.initial_slice(fragments, self.budget.admission_items, older))
            await self.prepare_fragments(
                (edge.fragments if local else fragments)[selected], lambda: snapshot.current(self),
            )
            async with window.history_lock:
                if not snapshot.current(self):
                    return
                if (self.pages[0] if older else self.pages[-1]) is not edge:
                    return
                if edge.capture_admission() != admission:
                    return
                # Source admission survives reader movement. Keep the reader's
                # row and the visible fragments, chosen after preparation.
                position = self.reader_position(window)
                protected = {id(fragment) for fragment in self.visible_fragments()}
                async with self.window.preserve_history(None, root=self, position=position):
                    await self._extend_and_trim(edge, older, local, page, protected, fragments, prepared)
                    self._require_publication()
        except _PublicationRetired:
            return
        finally:
            if self.state.accepts_publication:
                self.window.check_follow()

    async def _extend_and_trim(
        self, edge: TranscriptPageView, older: bool, local: bool,
        page: TranscriptPage | None, protected: set[int],
        fragments: tuple[TranscriptFragment, ...] | None,
        prepared: PreparedTranscriptPage | None = None,
    ) -> None:
        """Admit the next range and trim fragments the reader is not seeing.

        protected holds ids of fragments that must stay admitted: the visible
        ones and those just admitted for the reader's direction of travel.
        """
        async with self.lock:
            previous_start = self.pages[0], self.pages[0].start
            overlay_visible = self.filter.projection_visible()
            snapshot = self.source_snapshot()
            protected_pages: set[TranscriptPageView] = set()
            if local:
                previous = {id(fragment) for fragment in edge.admitted_fragments}
                if not await edge.prepared.extend(edge, older, lambda: snapshot.current(self)):
                    raise _PublicationRetired
                self._require_publication()
                protected.update(id(fragment) for fragment in edge.admitted_fragments
                                 if id(fragment) not in previous)
            elif page is not None:
                assert fragments is not None
                admission = edge.capture_admission()
                async with TranscriptPageView.acquire(
                    self, page, newest=older, fragments=fragments, batch_size=self.budget.admission_items,
                    prepared=prepared,
                    before=edge if older else self.newer,
                    current=lambda: snapshot.current(self) and edge.capture_admission() == admission,
                ) as view:
                    if older:
                        self.pages.appendleft(view)
                    else:
                        self.pages.append(view)
                protected.update(id(fragment) for fragment in view.admitted_fragments)
                protected_pages.add(view)
                await self._report_coverage(page, fragments)
            self._fragment_budget = limit = max(
                self.budget.item_limit(len(protected)), self._visible_fragment_budget(),
            )
            excess = self.fragment_count - limit
            trim_older = self._follow_source_tail or not older
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
                    members = list(candidate.admitted_fragments)
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

class ProjectedTranscriptHistory(TranscriptHistory):
    """A source projection with the ordinary pager's admission and eviction policy."""

    def __init__(self, owner: TranscriptHistory, source: ProjectedTranscriptSource,
                 prepared: PreparedTranscriptPage) -> None:
        self._projection_owner = ref(owner)
        super().__init__(prepared.page, source.loader, prepared=prepared, budget=owner.budget)
        self._page_buffer = source
        # Finish the container's native mount before awaiting row admission.
        # A slow/held row batch must not strand the page's own message pump in
        # Compose, where input-settlement barriers would wait on its startup.
        if not source.admitted:
            page = self.pages[0]
            page.prepared.select_admission(slice(page.start, page.start))
        self.add_class("filtered-history-results")

    @classmethod
    def from_source(cls, source: ProjectedTranscriptSource, *, owner: TranscriptHistory):
        if not source.admitted or source.closed:
            raise ValueError("No retained projected admission")
        history = cls(owner, source, source.admitted[0])
        history.pages.extend(TranscriptPageView(
            page.page, prepared=page, batch_size=owner.budget.admission_items,
        ) for page in source.admitted[1:])
        history._source_state = ParkedSourceTranscript(LiveTranscript())
        return history

    async def _finish_mount(self) -> None:
        # WorkingTranscript captures the actual window reader. Acquire that
        # operation only after the shared on_mount has bound native ancestry,
        # before observers may request another edge from this empty cohort.
        if self._source_state.accepts_source_work:
            self.reserve_source_work()
        await super()._finish_mount()

    @property
    def older_page_available(self) -> bool:
        return self.checkpoint_available and self.has_older

    def request_older(self) -> None:
        if self.older_page_available:
            self._request_page(True)

    async def load_older(self) -> None:
        if self.older_page_available:
            await self.reserve_source_work().execute(self, partial(self._load_page, True))

    async def admit_initial(self) -> None:
        await self._source_state.execute(self, self._admit_initial)

    async def _admit_initial(self) -> None:
        self._require_publication()
        snapshot = self.source_snapshot()
        if not await self.pages[0].prepared.extend(self.pages[0], False, lambda: snapshot.current(self)):
            raise _PublicationRetired
        self._require_publication()
        self._update_edges()

    @property
    def state(self) -> TranscriptState:
        return super().state.for_projection(self, self._projection_owner())

    @property
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        # Selection was applied by the source; the view never reinterprets it.
        return all_categories()

    @property
    def _follow_source_tail(self) -> bool:
        # This window is a historical prefix, not the live canonical tail.
        return False

    def _reader(self) -> PreparedPageSource:
        assert self._page_buffer is not None
        return self._page_buffer

    @property
    def coverage_events(self) -> Iterator[TranscriptEvent]:
        return (event for page in self.pages for fragment in page.fragments for event in fragment.events)

    async def _report_coverage(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        owner = self._projection_owner()
        if owner is not None and owner.filter.owns_projection(self):
            await owner._report_coverage(replace(page, events=tuple(
                event for fragment in fragments for event in fragment.events
            )), fragments)
