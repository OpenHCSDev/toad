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
from textual.widget import Widget
from textual.walk import walk_depth_first
from textual.strip import Strip
from textual.widgets import Static

from toad.transcript_filter import TranscriptFilter
from toad.transcript_state import TranscriptState, LiveTranscript, ProvisionalTranscript, ParkedSourceTranscript, LatestViewportRequest
from toad.transcript_source_preparation import TranscriptSourcePreparation
from toad.transcript_preparation import (
    CategoryProjection, PageRequest, PreparedPageSource, PreparedTranscriptPage, PageFragmentRange, TranscriptPageBuffer,
    ProjectedTranscriptSource,
)
from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from toad.widgets.message_divider import AgentActivityDivider, MessageClock
from toad.textual_colours import Animated
from ui_theme.effects import NEW_TEXT
from toad.widgets.presentation_window import PresentationBudget
from toad.line_blocks import ToggleDetails
from toad.message_rows import MessageRow
from toad.notification_status import CheckedNotifications, UnavailableNotifications, UncheckedNotifications
from toad.widgets.transcript_lines import (
    HorizontalRows, Lines, OpensMessageNames, PreparedLines, TranscriptLinesBatchRenderTask, TranscriptLinesRenderTask,
    selection_painted,
)
from toad.widgets.committed_presentation import CommittedHistory, TranscriptInputClaim
from toad.core.source_events import TranscriptCoverage
from toad.widgets.message_filter import (
    all_categories, CategorizedBlock, MessageCategory, apply_block_filter,
)
from toad.widgets.transcript_fragments import (
    Shown, TranscriptFragment, transcript_fragments,
)

if TYPE_CHECKING:
    from toad.line_blocks import LineBlock
    from toad.widgets.history_anchor import HistoryWindow

class _DrawingStopped(Exception):
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

class TranscriptPageView(Animated, HorizontalRows, Widget):
    """One transcript page, drawn as its admitted fragments' prepared lines.

    Fragments never become widgets. Styled rows come from the render worker
    processes; until they arrive a fragment draws its plain wrapped text.
    A page that arrived on the live tail rises out of the background.
    """

    DEFAULT_CSS = "TranscriptPageView { height: auto; overflow-x: auto; overflow-y: hidden; }"
    RENDER_BATCH = 8

    def __init__(self, page: TranscriptPage, *, newest: bool = True,
                 fragments: tuple[TranscriptFragment, ...] | None = None,
                 batch_size: int = PreparedTranscriptPage.BATCH,
                 prepared: PreparedTranscriptPage | None = None, fresh: bool = False):
        self.fresh = fresh
        self.prepared = prepared if prepared is not None else PreparedTranscriptPage(
            page, transcript_fragments(page.events) if fragments is None else
            tuple(fragments), 0,
        )
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
        self._first_row: dict[int, int] = {}
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
    def batch_size(self):
        return self.prepared.batch_size

    @batch_size.setter
    def batch_size(self, size):
        self.prepared.batch_size = size

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
        self.app.theme_changed_signal.subscribe(self, self._theme_changed)
        if self.fresh:
            # Once: a page moved to another parent has not arrived again.
            self.fresh = False
            self.run_effect(NEW_TEXT)

    def _theme_changed(self, _theme) -> None:
        from toad.widgets.history_anchor import HistoryWindow

        # Lines hold resolved theme colours; a new theme draws new lines,
        # plain ones first, which wrap to other rows than the styled ones.
        self.query_ancestor(HistoryWindow).keep_reader()
        self.range_changed()

    def on_unmount(self) -> None:
        self.stop_effect()
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
            lines = fragment.plain_lines(width, theme)
        return lines

    def _measure(self, width: int) -> None:
        self._width, self._measured = width, True
        self._pending.clear()
        layout, starts, y = [], [], 0
        if width > 0:
            for fragment in self.fragments_in_range:
                if not fragment.shown_in(self.visible_categories):
                    continue
                # Layout needs only the row count; rows and strips are
                # built when a row is drawn, so a width change draws no text.
                lines = self._lines(fragment, width)
                layout.append((fragment, y, lines))
                starts.append(y)
                y += lines.height
        self._layout, self._starts, self._height = layout, starts, y
        self._first_row = {id(fragment): first for fragment, first, _lines in layout}
        if self._pending and self.is_attached and (self._render_task is None or self._render_task.done()):
            # Layout calls this to measure: start the renderer in its own loop
            # turn, not inside the measurement (the task factory is eager).
            self._render_task = asyncio.create_task(self._render_pending(), eager_start=False)

    @height_dependency(INDEPENDENT_HEIGHT)
    def get_content_height(self, container, viewport, width: int) -> int:
        # The admitted fragments wrapped at this width: the container's height
        # is never read, so an arrangement measured at height 0 is reused.
        if width != self._width or not self._measured:
            self._measure(width)
        return self._height

    def render_line(self, y: int) -> Strip:
        # Layout supplies the width through get_content_height; reading size
        # here would look this widget up in the compositor for every row.
        width = self._width
        slot = bisect_right(self._starts, y) - 1
        if slot < 0:
            return selection_painted(self, self.blank_row(width), y)
        fragment, first, lines = self._layout[slot]
        row = y - first
        if row >= lines.height:
            return selection_painted(self, self.blank_row(width), y)
        # Prepared rows span exactly this width (Lines.strips_at).
        strip = lines.strips_at(fragment.link_place)[row]
        if self.animation is not None:
            strip = self.app.colours.paint_rising(self.animation.frame(), strip)
        return selection_painted(self, self.on_background(strip), y)

    def fragment_row(self, fragment: TranscriptFragment) -> tuple[int, bool] | None:
        """Where an admitted fragment is in this page: its first measured row, and whether it is drawn.

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
            if (first := self._first_row.get(id(candidate))) is not None:
                return first, candidate is fragment
        return self._height, False

    @property
    def drawn_fragments(self) -> tuple[TranscriptFragment, ...]:
        """The fragments this page draws rows for, oldest first."""
        return tuple(fragment for fragment, _first, _lines in self._layout)

    def fragment_rows(self, fragment: TranscriptFragment) -> range | None:
        """The rows of this page that draw a fragment."""
        for candidate, first, lines in self._layout:
            if candidate is fragment:
                return range(first, first + lines.height)
        return None

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
        for fragment, first, lines in self._layout:
            if first < bottom and first + lines.height > top:
                yield fragment, range(max(0, top - first), min(lines.height, bottom - first)), lines

    def visible_fragments(self, window) -> tuple[TranscriptFragment, ...]:
        """The fragments this page draws inside the window's viewport."""
        return tuple(fragment for fragment, _rows, _lines in self.visible_rows(window))

    def _nearest_pending(self) -> list[TranscriptFragment]:
        from toad.widgets.history_anchor import HistoryWindow

        window = self.query_ancestor(HistoryWindow)
        rows = self._first_row
        pending = list(self._pending.values())
        # On screen, style the rows nearest the reader first. An off-screen
        # page (prepared ahead) has no reader row; its order does not matter.
        if (offset := window.placed_row(self)) is not None:
            reader = window.scroll_y - offset
            pending.sort(key=lambda fragment: abs(rows[id(fragment)] - reader))
        return pending[:self.RENDER_BATCH]

    async def _render_pending(self) -> None:
        renderer = self.app.render_processes
        while self._pending and self.is_attached:
            batch = self._nearest_pending()
            if not batch:
                return
            for fragment in batch:
                del self._pending[id(fragment)]
            width, theme = self._width, self.app.colours.line_theme
            tasks = tuple(TranscriptLinesRenderTask(fragment.line_blocks, width, theme)
                          for fragment in batch)
            results = await renderer.submit(TranscriptLinesBatchRenderTask(tasks))
            if not self.is_attached or width != self._width:
                continue
            await self._publish([(fragment, task.blocks, lines)
                                 for fragment, task, lines in zip(batch, tasks, results)])

    async def _publish(self, ready: list[tuple[TranscriptFragment, tuple[LineBlock, ...], PreparedLines]]) -> None:
        from toad.widgets.history_anchor import HistoryWindow

        window = self.query_ancestor(HistoryWindow)
        async with window.preserve_history(root=self):
            theme = self.app.colours.line_theme
            for fragment, blocks, lines in ready:
                fragment.hold_lines(theme, lines, blocks)
            self.range_changed()

    def retain_sources(self) -> None:
        """Pages hold immutable fragments; nothing native to transfer."""
        self.prepared.retain_sources(self)
        self.prepared.retained_bytes = 0

    @classmethod
    @asynccontextmanager
    async def acquire(
        cls, owner: LineHistory, page: TranscriptPage, *, fragments,
        batch_size: int, before: Widget, current: Callable[[], bool], newest: bool = True,
        prepared: PreparedTranscriptPage | None = None, fresh: bool = False,
    ) -> AsyncIterator[TranscriptPageView]:
        """Acquire a page until its original source transfers native custody."""
        view = cls(page, fragments=fragments, prepared=prepared, batch_size=batch_size, newest=newest,
                   fresh=fresh)
        view.prepared.set_fragment_range(PreparedTranscriptPage.initial_slice(view.fragments, batch_size, newest))
        view.prepared.retain_sources(view)
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
        window = self.query_ancestor(LineHistory).window
        async with window.history_lock:
            if not current():
                return False
            async with window.preserve_history(root=self):
                return await self.prepared.replace_range(self, self.fragments, selected, None, current)


class LineHistory(OpensMessageNames, TranscriptSourcePreparation, ConversationBlock, CategorizedBlock, VerticalGroup):
    """History drawn as lines, a bounded range of pages at a time.

    It owns paging in both directions, lookahead, trimming, the jump to the
    newest page and the reader's position. A subclass says what its source is:
    `TranscriptHistory` for a saved transcript, `WireHistory` for a channel or
    direct conversation.
    """

    CACHE_SUBTREE_GEOMETRY = True
    MAX_FRAGMENTS = 240
    NOTIFICATION_GROUP = "message-notifications"

    @property
    def message_category(self) -> None:
        return None

    @cached_property
    def block_cursor(self):
        return FragmentBlockCursor(self)

    def __init__(self, page: TranscriptPage, loader: Callable[..., Awaitable[TranscriptPage]] | None = None,
                  *, fragments: tuple[TranscriptFragment, ...] | None = None,
                  budget: PresentationBudget | None = None,
                  prepared: PreparedTranscriptPage | None = None,
                  source_state: TranscriptState | None = None):
        super().__init__(source_state=source_state or LiveTranscript())
        self.loader, self.through = loader, page.after
        self.budget = budget or PresentationBudget(
            max_items=self.MAX_FRAGMENTS, batch_items=PreparedTranscriptPage.BATCH,
        )
        self.pages = deque([TranscriptPageView(
            page, fragments=fragments, prepared=prepared, batch_size=self.budget.batch_items,
        )])
        self.older = HistoryEdge("↑ Earlier history loads as you scroll")
        self.older.tooltip = "Click or press Enter to load earlier history, including in In/out only mode"
        self.newer = JumpToLatest("↓ Jump to latest")
        self.filter = TranscriptFilter(self)
        self._fragment_budget = self.budget.max_items
        # Bound when mounted; a history closed before its mount has no window to leave.
        self.window: HistoryWindow | None = None

    def resume_source(self) -> None:
        super().resume_source()
        if (projection := self.filter.state.overlay) is not None:
            projection.resume_source()

    async def prepare_fragments(self, fragments, current: Callable[[], bool], *, selected=None) -> None:
        """Render fragments' lines at the page width before they are admitted."""
        width = self.line_width
        if width <= 0:
            return
        theme = self.app.colours.line_theme
        selected = self.selected_categories if selected is None else selected
        todo = [fragment for fragment in fragments
                if fragment.shown_in(selected) and fragment.lines_for(width, theme) is None]
        renderer = self.app.render_processes
        for first in range(0, len(todo), self.budget.batch_items):
            if not current():
                return
            batch = todo[first:first + self.budget.batch_items]
            tasks = tuple(TranscriptLinesRenderTask(fragment.line_blocks, width, theme) for fragment in batch)
            results = await renderer.submit(TranscriptLinesBatchRenderTask(tasks))
            for fragment, task, lines in zip(batch, tasks, results):
                fragment.hold_lines(theme, lines, task.blocks)

    @property
    def line_width(self) -> int:
        """The width pages draw at, as laid out; 0 before the first layout."""
        return next((page.line_width for page in self.pages if page.line_width), 0)

    async def prepare_body(self, current: Callable[[], bool], *, selected=None) -> None:
        """Warm the actual page admissions, including a restored reader range."""
        if (projection := self.filter.state.overlay) is not None:
            await projection.prepare_body(current)
        for page in self.pages:
            await self.prepare_fragments(page.fragments_in_range,
                                         current, selected=selected)

    @property
    def fragments_in_range(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.fragments_in_range)

    def visible_fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.visible_fragments(self.window))

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        self.check_notifications()

    # Core feedback for every visible bus message, native or wire.

    def check_notifications(self) -> None:
        if not self.can_draw_on_screen or any(
            worker.node is self and worker.group == self.NOTIFICATION_GROUP and not worker.is_finished
            for worker in self.workers
        ):
            return
        fragments = self._notified_fragments()
        if fragments:
            self.run_worker(self._read_notifications(fragments), group=self.NOTIFICATION_GROUP)

    def _notified_fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for fragment in self.visible_fragments() if fragment.checks_notifications)

    async def read_notifications(self, references):
        from toad.widgets.conversation import Conversation

        return await self.query_ancestor(Conversation).transcript.get_message_notifications(references)

    async def _read_notifications(self, fragments: tuple[TranscriptFragment, ...]) -> None:
        # Outcomes belong to original references, not a page generation or
        # its growing tail. The read binding fences the bus; visible membership
        # and this publisher's lifetime fence where its answer can be drawn.
        while fragments and self.can_draw_on_screen:
            revision = self.app.coordination_access.revision
            references = tuple(dict.fromkeys(
                reference for fragment in fragments for reference in fragment.notification_references))
            try:
                results = await self.read_notifications(references)
            except (OSError, ValueError, RuntimeError) as failure:
                statuses = [UnavailableNotifications(str(failure))] * len(fragments)
            else:
                statuses = [CheckedNotifications.for_references(fragment.notification_references, results)
                            for fragment in fragments]
            if not self.can_draw_on_screen:
                return
            visible = {id(fragment) for fragment in self._notified_fragments()}
            await self._show([(fragment, replace(fragment.shown, status=status))
                              for fragment, status in zip(fragments, statuses) if id(fragment) in visible])
            if not self.can_draw_on_screen:
                return
            # Newcomers need their first check; checked rows need another
            # answer only when Core changed during the read or paint.
            fragments = tuple(fragment for fragment in self._notified_fragments()
                              if revision != self.app.coordination_access.revision
                              or isinstance(fragment.shown.status, UncheckedNotifications))

    # What a fragment shows

    async def _show(self, changes: list[tuple[TranscriptFragment, Shown]]) -> None:
        """Change what fragments draw: render the new lines first, then swap them in one frame."""
        changes = [(fragment, shown) for fragment, shown in changes if shown != fragment.shown]
        if not changes:
            return
        width, theme = self.line_width, self.app.colours.line_theme
        in_range = {id(fragment) for fragment in self.fragments_in_range}
        drawn = [(fragment, shown) for fragment, shown in changes if id(fragment) in in_range and width > 0]
        lines = await self.app.render_processes.submit(TranscriptLinesBatchRenderTask(tuple(
            TranscriptLinesRenderTask(fragment.blocks(shown), width, theme)
            for fragment, shown in drawn))) if drawn else ()
        if not self.state.can_draw:
            return
        ready = {id(fragment): rows for (fragment, _shown), rows in zip(drawn, lines)}
        async with self.window.preserve_history(root=self):
            for fragment, shown in changes:
                fragment.show(shown, theme, ready.get(id(fragment)))
            for page in self.pages:
                page.range_changed()
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
            first, drawn = placed
            if drawn:
                self.window.reader_position = FragmentPosition(fragment, first, first)
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
        return self.through, self.filter.state, tuple(page.capture_range() for page in self.pages)

    def capture_reader_ranges(self) -> tuple[PageFragmentRange, ...]:
        """Retain the original source ranges that a returning reader needs."""
        for page in self.pages:
            page.retain_sources()
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
                if not await page.select_range(slice(page_range.start, page_range.stop), current,
                                               suppliers=page_range.members):
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
            PreparedTranscriptPage(page.page, page.fragments[:page.start], 0),
            self.loader, self.app.preparation, CategoryProjection(selected),
            upstream=self._reader() if self.loader is not None else None,
        )

    @property
    def _follow_source_tail(self) -> bool:
        return self.window.follows_tail

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
        from toad.widgets.history_anchor import HistoryWindow
        self.window = self.query_ancestor(HistoryWindow)
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
    def selected_categories(self) -> frozenset[type[MessageCategory]]:
        from toad.widgets.conversation import Contents, Conversation

        # A nested pager inherits the outer message's category, not the
        # synthetic role of its Markdown fragments.
        return (self.query_ancestor(Conversation).visible_categories
                if self.is_attached and isinstance(self.parent, Contents) else all_categories())

    @property
    def source_checkpoint_available(self) -> bool:
        return self.filter.checkpoint_available

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

    @property
    def drawn_extent(self) -> tuple[int, int]:
        pages = [page for page in self.pages if page.line_count]
        return sum(page.line_count for page in pages), sum(page.stop - page.start for page in pages)

    @property
    def destination_needs_older(self) -> bool:
        """Whether the followed destination still leaves viewport rows uncovered."""
        return (self.has_older and self._follow_source_tail
                and self.drawn_extent[0] < self.window.scrollable_content_region.height)

    def prepare_scroll(self) -> None:
        if (self.loader is None or not self.is_mounted or not self.state.can_draw or not self.screen.is_current
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
        ranges = tuple(page.capture_range() for page in pages)
        self.request_lookahead((reader, edges, rounds, count, demand, pages, ranges,
                                self.source_snapshot()))

    async def prepare_lookahead(self, intent) -> None:
        reader, edges, rounds, count, demand, pages, ranges, snapshot = intent
        current = partial(self.lookahead_current, intent)
        for page in pages:
            await page.prepare_adjacent(self, demand, count, current)
        async for prepared in reader.prefetch(*edges, current, rounds=rounds):
            await self.prepare_fragments(
                demand.neighbors(prepared.fragments, len(prepared.fragments), 0, count), current,
            )

    def lookahead_current(self, intent) -> bool:
        reader, _edges, _rounds, _count, demand, pages, ranges, snapshot = intent
        return (snapshot.current(self)
                and snapshot.window.lookahead.accepts(demand)
                and all(page.capture_range() == page_range
                        for page, page_range in zip(pages, ranges)))

    def _size_updated(self, size, virtual_size, container_size, layout=True) -> bool:
        # Edges are read from this history's laid-out box. A check made
        # before layout gave it one (a filter just chosen, a first page) finds
        # none, and a history shorter than its window changes no size but its own.
        changed = super()._size_updated(size, virtual_size, container_size, layout)
        if changed:
            self.request_preparation()
        return changed

    def _check_edges(self) -> None:
        if (not self.checkpoint_available
                or not self.screen.is_active or not self.selected_categories):
            return
        runway = self._runway()
        if runway is None:
            return
        above, below = runway
        # Original published geometry admits source work, even while a body is
        # preparing. Its worker owns read/prepare/native mutation; the existing
        # viewport frame owner alone decides when those bodies may be painted.
        if self._follow_source_tail and self.has_newer:
            self._request_page(False)
            return
        if self.filter.active:
            self.filter.check_edges()
            return
        if self.destination_needs_older:
            # A destination is a bottom viewport, not one transport page. Fill
            # its visible rows before upward input has scroll travel to spend.
            self._request_page(True)
        elif self.has_older and not self._follow_source_tail and above <= self.prefetch_distance:
            self._request_page(True)
        elif self.has_newer and below <= self.prefetch_distance:
            self._request_page(False)

    def _runway(self) -> tuple[int, int] | None:
        """Drawn rows above and below the window's viewport; None while this history is off screen."""
        # Off-screen pagers must not ask for their region: after a scroll that
        # falls back to rebuilding geometry for the *whole* mounted transcript.
        # The layout signal also calls us once this pager enters the viewport.
        visible = self.screen._compositor.visible_widgets
        geometry, window = visible.get(self), visible.get(self.window)
        if geometry is None or window is None or not geometry[0].overlaps(window[0]):
            return None
        region, viewport = geometry[0], window[0]
        return viewport.y - region.y, region.bottom - viewport.bottom

    def _edge_batch(self, older: bool) -> int:
        """How many fragments one load draws beyond an edge: those that fill the rows missing ahead of the reader."""
        runway = self._runway()
        missing = 0 if runway is None else self.prefetch_distance - runway[0 if older else 1]
        return self.window.lookahead.fragments_for(missing)

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
        destination_batch = window.lookahead.destination_batch(self.budget, window.outer_size.height)
        view = self.pages[-1]
        if loader is None or view.page.after == self.through:
            # The original source already supplies the newest cut. End moves
            # its native demand; another read cannot improve its coverage.
            prepared = view.prepared
        else:
            prepared = await self._reader().get(PageRequest(before=self.through))
        page, fragments = prepared.page, prepared.fragments
        selected = PreparedTranscriptPage.initial_slice(fragments, destination_batch, True)
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
            view.batch_size = destination_batch
            if not await view.select_range(
                selected, lambda: snapshot.current(self) and request.current(window),
            ):
                return False
        async with window.history_lock:
            if not snapshot.current(self) or not request.current(window):
                return False
            async with window.preserve_history(root=self):
                previous = tuple(self.pages)
                if prepared is view.prepared:
                    self.pages = deque([view])
                else:
                    try:
                        async with TranscriptPageView.acquire(
                            self, page, fragments=fragments, batch_size=destination_batch,
                            prepared=prepared,
                            before=self.newer, current=lambda: snapshot.current(self) and request.current(window),
                        ) as view:
                            self.pages = deque([view])
                    except _DrawingStopped:
                        return False
                self.remove_children(tuple(retired for retired in previous if retired is not view))
                self._update_edges()
            return True

    async def _load_page(self, older: bool, prepared: PreparedTranscriptPage | None = None,
                         *, fresh: bool = False) -> None:
        """Draw the next range beyond an edge; `prepared` is that page when the caller read it.

        `fresh` when the page just arrived on the live tail rather than being paged to."""
        initial_count = self.fragment_count
        snapshot = self.source_snapshot()
        window, loader = snapshot.window, self.loader
        edge = self.pages[0] if older else self.pages[-1]
        page_range = edge.capture_range()
        try:
            local = edge.start > 0 if older else edge.stop < len(edge.fragments)
            page = None
            fragments = None
            if not local:
                if loader is None:
                    return
                if prepared is None:
                    prepared = await self._reader().get(PageRequest(
                        before=edge.page.before if older else None,
                        after=edge.page.after if not older else None,
                    ))
                page, fragments = prepared.page, prepared.fragments
            # One load fills the rows missing ahead of the reader, however
            # few rows each fragment draws.
            edge.batch_size = self._edge_batch(older)
            selected = (edge.prepared.extension_slice(older) if local
                        else PreparedTranscriptPage.initial_slice(fragments, edge.batch_size, older))
            await self.prepare_fragments(
                (edge.fragments if local else fragments)[selected], lambda: snapshot.current(self),
            )
            async with window.history_lock:
                if not snapshot.current(self):
                    return
                if (self.pages[0] if older else self.pages[-1]) is not edge:
                    return
                if edge.capture_range() != page_range:
                    return
                # The fragments the reader sees stay admitted; they are chosen
                # after preparation, which the reader may have scrolled through.
                protected = {id(fragment) for fragment in self.visible_fragments()}
                async with self.window.preserve_history(root=self):
                    await self._extend_and_trim(edge, older, local, page, protected, fragments, prepared,
                                                fresh=fresh)
                    self._require_can_draw()
            # The destination request spans transport pages. Keep its one
            # admitted worker until the rendered bottom viewport is covered.
            if older and self.fragment_count > initial_count and self.destination_needs_older:
                await self._load_page(True)
        except _DrawingStopped:
            return
        finally:
            if self.state.can_draw:
                self.window.check_follow()

    async def _extend_and_trim(
        self, edge: TranscriptPageView, older: bool, local: bool,
        page: TranscriptPage | None, protected: set[int],
        fragments: tuple[TranscriptFragment, ...] | None,
        prepared: PreparedTranscriptPage | None = None, *, fresh: bool = False,
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
                previous = {id(fragment) for fragment in edge.fragments_in_range}
                if not await edge.prepared.extend(edge, older, lambda: snapshot.current(self)):
                    raise _DrawingStopped
                self._require_can_draw()
                protected.update(id(fragment) for fragment in edge.fragments_in_range
                                 if id(fragment) not in previous)
            elif page is not None:
                assert fragments is not None
                page_range = edge.capture_range()
                async with TranscriptPageView.acquire(
                    self, page, newest=older, fragments=fragments, batch_size=edge.batch_size,
                    prepared=prepared, fresh=fresh,
                    before=edge if older else self.newer,
                    current=lambda: snapshot.current(self) and edge.capture_range() == page_range,
                ) as view:
                    if older:
                        self.pages.appendleft(view)
                    else:
                        self.pages.append(view)
                protected.update(id(fragment) for fragment in view.fragments_in_range)
                protected_pages.add(view)
                await self._page_added(page, fragments)
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


class TranscriptHistory(LineHistory, CommittedHistory):
    """The line history of a saved transcript.

    Its pages stand in for the conversation's live blocks: it reports which
    events it covers, follows the committed end of the transcript, and can be
    parked with a tab and rebuilt from what was parked.
    """

    def __init__(self, page: TranscriptPage, loader: Callable[..., Awaitable[TranscriptPage]] | None = None,
                 *, committed: bool = True, **kwargs):
        super().__init__(page, loader, **kwargs,
                         source_state=LiveTranscript() if committed else ProvisionalTranscript())

    async def park_document(self) -> PreparedPageSource:
        """Stop reading and hand the drawn pages to their reader, to be rebuilt when the tab returns."""
        await self.retire_source(parked=True)
        source = self._reader()
        projection = self.filter.state.overlay
        projected = await projection.park_document() if projection is not None else None
        for page in self.pages:
            page.retain_sources()
        pages = tuple(page.prepared for page in self.pages)
        position = self.window.reader_position
        await source.runtime.run_thread(source.measure_held, pages, projected,
                                        () if position is None else position.ranges)
        source.park(pages, projected)
        return source

    @classmethod
    def from_source(cls, source: PreparedPageSource) -> TranscriptHistory:
        """Rebuild a parked history from its pages; it covers no live blocks until it resumes."""
        pages = source.held_pages
        if not pages or source.closed:
            raise ValueError("No retained transcript admission")
        history = cls(pages[0].page, source.loader, prepared=pages[0])
        history.through = source.through
        history._page_buffer = source
        history._source_state = ParkedSourceTranscript(LiveTranscript())
        history.pages.extend(TranscriptPageView(
            page.page, prepared=page, batch_size=history.budget.batch_items,
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

    def source_resumed(self) -> None:
        if self._source_state.reports_coverage:
            self.publish_core(TranscriptCoverage(tuple(self.coverage_events)))

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        if self._source_state.reports_coverage:
            from toad.widgets.conversation import Conversation
            # The live blocks this page covers are retired as part of adding
            # the page, without holding the conversation's message pump. A
            # saved viewer outside a conversation has no live blocks.
            for ancestor in self.ancestors:
                if isinstance(ancestor, Conversation):
                    ancestor.transcript.covered(TranscriptCoverage(page.events), self).call_when_ready(ancestor)
                    break

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
        return (event for page in self.pages for event in page.page.events)

    def covers_incoming(self, sequence: int) -> bool:
        if not self._source_state.reports_coverage:
            return False
        if self.committed_cursor.covers_incoming(sequence):
            return True
        if sequence in TranscriptCoverage(tuple(self.coverage_events)).sequences:
            return True
        return self.filter.covers_incoming(sequence)

    def covers_input(self, native_id: str | None) -> bool:
        """Whether the loaded saved pages hold the input Core started under this identity."""
        return (self._source_state.reports_coverage
                and native_id in TranscriptCoverage(tuple(self.coverage_events)).native_inputs)

    @property
    def committed_cursor(self) -> TranscriptCursor:
        return self.through

    def retain_committed(self, through: TranscriptCursor) -> None:
        """Extend access to saved source without moving the displayed page window."""
        if not self.accepts_commit(through):
            raise ValueError("Commit replaces or rewinds the retained source")
        self.extend_source(through)

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
            if not is_current() or not self.state.can_draw:
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
        if not source.held_pages:
            page = self.pages[0]
            page.prepared.set_fragment_range(slice(page.start, page.start))
        self.add_class("filtered-history-results")

    @classmethod
    def from_source(cls, source: ProjectedTranscriptSource, *, owner: TranscriptHistory):
        if not source.held_pages or source.closed:
            raise ValueError("No retained projected admission")
        history = cls(owner, source, source.held_pages[0])
        history.pages.extend(TranscriptPageView(
            page.page, prepared=page, batch_size=owner.budget.batch_items,
        ) for page in source.held_pages[1:])
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

    async def draw_initial(self) -> None:
        await self._source_state.execute(self, self._draw_initial)

    async def _draw_initial(self) -> None:
        self._require_can_draw()
        snapshot = self.source_snapshot()
        if not await self.pages[0].prepared.extend(self.pages[0], False, lambda: snapshot.current(self)):
            raise _DrawingStopped
        self._require_can_draw()
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

    async def _page_added(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        owner = self._projection_owner()
        if owner is not None and owner.filter.owns_projection(self):
            await owner._page_added(replace(page, events=tuple(
                event for fragment in fragments for event in fragment.events
            )), fragments)
