"""Bounded, cursor-paged saved history; all transcript interpretation is model-owned."""

from __future__ import annotations

from toad.widgets.message_filter import OtherCategory

import asyncio
from collections import deque
from dataclasses import replace
from collections.abc import Awaitable, Callable, Iterator
from typing import TYPE_CHECKING
from weakref import ref

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent, ContextTranscript, UserTranscript, AgentTextTranscript,
    ThinkingTranscript, LiveTextTranscript, ToolTranscript, ToolStartTranscript, ToolEndTranscript,
)
from agent_comms.tool_results import tool_result_content
from agent_comms.backend import tool_kind
from textual import events, on
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from toad.acp import protocol
from toad.acp.encode_tool_call_id import encode_tool_call_id
from toad.transcript_preparation import (
    CategoryProjection, PageRequest, PreparedPageSource, PreparedTranscriptPage,
    ProjectedTranscriptSource, TranscriptPageBuffer, incoming_sequences,
)
from toad.widgets.agent_response import AgentResponse, ResponseDelivery
from toad.widgets.agent_thought import AgentThought
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from toad.widgets.message_divider import AgentActivityDivider
from toad.widgets.history_anchor import HistoryAnchor
from toad.widgets.presentation_window import PresentationBudget, protected_presentations
from toad.widgets.committed_presentation import CommittedHistory
from toad.widgets.message_filter import (
    all_categories, CategorizedBlock, MessageCategory, apply_block_filter, event_category,
)
from toad.widgets.transcript_fragments import (
    TranscriptFragment, prepare_transcript_fragments, transcript_fragments,
)

if TYPE_CHECKING:
    from toad.widgets.conversation import Window



class _PublicationRetired(Exception):
    """Unwind an anchor transaction whose source owner no longer publishes."""


class TranscriptBlockConsumer(MroDispatch):
    def __init__(self, *, fragment: bool, show_divider: bool):
        self.blocks: list[Widget] = []
        self.tools: dict[str, protocol.ToolCall] = {}
        self.fragment = fragment
        self.show_divider = show_divider

    @handles(ContextTranscript)
    def context(self, event: ContextTranscript):
        from toad.widgets.coordination_context import CoordinationContext
        self.blocks.append(CoordinationContext(event.text))

    @handles(UserTranscript)
    def user(self, event: UserTranscript):
        if event.routed:
            from toad.widgets.incoming_message import IncomingMessage
            message = event.routing.requests[0]
            self.blocks.append(IncomingMessage(
                message.sender, event.text, message.target, show_header=self.show_divider,
                sequence=message.seq,
            ))
        else:
            self.blocks.append(UserInput(event.text, show_divider=self.show_divider))

    @handles(AgentTextTranscript)
    def agent(self, event: AgentTextTranscript):
        self.blocks.append(AgentResponse(
            event.text, delivery=ResponseDelivery.from_route(event.routing.reply if event.routing else None),
            category=event_category(event), paginate=not self.fragment,
            show_divider=self.show_divider,
        ))

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript):
        self.blocks.append(AgentThought(event.text, paginate=not self.fragment))

    def tool(self, event: ToolTranscript) -> protocol.ToolCall:
        tool_id = event.tool_call_id
        if tool_id not in self.tools:
            self.tools[tool_id] = {
                "sessionUpdate": "tool_call", "toolCallId": tool_id,
                "title": event.tool_name or "Tool", "status": "completed",
                "kind": tool_kind(event.tool_name),
            }
            self.blocks.append(ToolCall(self.tools[tool_id], id=encode_tool_call_id(tool_id)))
        return self.tools[tool_id]

    @handles(ToolStartTranscript)
    def tool_start(self, event: ToolStartTranscript):
        self.tool(event)["rawInput"] = event.raw_input

    @handles(ToolEndTranscript)
    def tool_end(self, event: ToolEndTranscript):
        tool = self.tool(event)
        tool["status"] = "completed" if event.ok else "failed"
        tool["content"] = tool_result_content(event.tool_call_id, event.text, event.diff)


def transcript_blocks(events: tuple[TranscriptEvent, ...], *, fragment: bool = False,
                      show_divider: bool = True) -> list[Widget]:
    consumer = TranscriptBlockConsumer(fragment=fragment, show_divider=show_divider)
    for event in events:
        consumer.dispatch_sync(event)
    return consumer.blocks


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


class TranscriptFragmentView(CategorizedBlock, VerticalGroup):
    CACHE_HEIGHT_INDEPENDENT_BOX = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True

    def __init__(self, fragment: TranscriptFragment, selected=None):
        selected = all_categories() if selected is None else selected
        super().__init__()
        self.fragment = fragment
        self._message_category = (event_category(fragment.events[0]) if fragment.events
                                  else OtherCategory)
        self.add_class(f"-message-{self._message_category.declared_name}")
        self.set_class(not any(event.routed for event in fragment.events), "-unrouted")
        self.set_categories(selected)

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._message_category

    def set_categories(self, selected: frozenset[type[MessageCategory]]) -> None:
        self._selected_categories = selected
        apply_block_filter(self, selected)

    def compose(self) -> ComposeResult:
        # A semantic fragment may be one oversized paragraph, list, or fence.
        # It is already a page leaf: re-paging it would recursively remount the
        # same indivisible block forever without producing visible Markdown.
        if self.fragment.starts_agent_activity and not self.fragment.continuation:
            yield AgentActivityDivider(self._message_category)
        yield from transcript_blocks(
            self.fragment.events, fragment=True, show_divider=not self.fragment.continuation,
        )

    async def update_fragment(self, fragment: TranscriptFragment) -> None:
        """Keep a live text leaf and its routing controls when only text changed.

        A tool/result or routing change still requires normal recomposition.
        Updating Markdown itself preserves the outer scene, subscriptions and
        styles instead of destroying and reconstructing the entire fragment.
        """
        previous_fragment = self.fragment
        old_events, new_events = previous_fragment.events, fragment.events
        self.fragment = fragment
        category = event_category(new_events[0]) if new_events else OtherCategory
        if category != self._message_category:
            self.remove_class(f"-message-{self._message_category.declared_name}")
            self.add_class(f"-message-{category.declared_name}")
            self._message_category = category
            apply_block_filter(self, self._selected_categories)
        self.set_class(not any(event.routed for event in new_events), "-unrouted")
        if (len(old_events) == len(new_events) == 1
                and isinstance(old_events[0], LiveTextTranscript)
                and type(new_events[0]) is type(old_events[0])
                and replace(old_events[0], text=new_events[0].text) == new_events[0]
                and previous_fragment.starts_agent_activity == fragment.starts_agent_activity
                and previous_fragment.continuation == fragment.continuation
                and (len(self.children) == 1 or
                     (len(self.children) == 2 and isinstance(self.children[0], AgentActivityDivider)))):
            leaf = self.children[-1]
            if isinstance(leaf, (AgentResponse, AgentThought)):
                await leaf.update(new_events[0].text)
                return
        await self.recompose()


class TranscriptPageView(VerticalGroup):
    CACHE_HEIGHT_INDEPENDENT_BOX = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True
    BATCH = 4

    def __init__(self, page: TranscriptPage, *, newest: bool = True,
                 fragments: tuple[TranscriptFragment, ...] | None = None,
                 batch_size: int = BATCH):
        super().__init__()
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        self.batch_size = batch_size
        self.page = page
        self.fragments = transcript_fragments(page.events) if fragments is None else fragments
        self.start = max(0, len(self.fragments) - self.batch_size) if newest else 0
        self.stop = min(len(self.fragments), self.start + self.batch_size)
        self.visible_categories = all_categories()

    def compose(self) -> ComposeResult:
        for fragment in self.fragments[self.start:self.stop]:
            yield TranscriptFragmentView(fragment, self.visible_categories)

    def set_categories(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.visible_categories = selected
        for child in self.children:
            child.set_categories(selected)

    async def extend(self, older: bool) -> None:
        start = max(0, self.start - self.batch_size) if older else self.stop
        stop = self.start if older else min(len(self.fragments), self.stop + self.batch_size)
        widgets = [TranscriptFragmentView(fragment, self.visible_categories) for fragment in self.fragments[start:stop]]
        await self.mount(*widgets, before=self.children[0] if older and self.children else None)
        if older:
            self.start = start
        else:
            self.stop = stop

    async def trim(self, count: int, *, older: bool) -> None:
        children = list(self.children)
        await self.remove_children(children[:count] if older else children[-count:])
        if older:
            self.start += count
        else:
            self.stop -= count

    async def update_fragments(self, fragments: tuple[TranscriptFragment, ...], follow: bool) -> None:
        previous = {self.start + index: child for index, child in enumerate(self.children)}
        self.fragments = fragments
        stop = len(fragments) if follow else min(self.stop, len(fragments))
        start = max(0, stop - self.batch_size) if follow else min(self.start, stop)
        for index, child in previous.items():
            if not start <= index < stop:
                await child.remove()
        for index in range(start, stop):
            child = previous.get(index)
            if child is None:
                await self.mount(TranscriptFragmentView(fragments[index], self.visible_categories))
            elif child.fragment != fragments[index]:
                await child.update_fragment(fragments[index])
        self.start, self.stop = start, stop


class TranscriptHistory(CommittedHistory, CategorizedBlock, VerticalGroup):
    CACHE_HEIGHT_INDEPENDENT_BOX = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True
    MAX_FRAGMENTS = 24

    @property
    def message_category(self) -> None:
        return None

    def __init__(self, page: TranscriptPage, loader: Callable[..., Awaitable[TranscriptPage]] | None = None,
                  *, fragments: tuple[TranscriptFragment, ...] | None = None,
                  budget: PresentationBudget | None = None, committed: bool = True):
        super().__init__()
        self._committed = committed
        self.budget = budget or PresentationBudget(
            max_items=self.MAX_FRAGMENTS, admission_items=TranscriptPageView.BATCH,
        )
        self.pages = deque([TranscriptPageView(
            page, fragments=fragments, batch_size=self.budget.admission_items,
        )])
        self.loader = loader
        self.through = page.after
        self.older = HistoryEdge("↑ Earlier history loads as you scroll")
        self.older.tooltip = "Click or press Enter to load earlier history, including in In/out only mode"
        self.newer = JumpToLatest("↓ Jump to latest")
        self._loading = False
        self._advancing = False
        self._check_pending = False
        self._saturated_widget_limit = 0
        self._generation = 0
        self._filter_overlay: ProjectedTranscriptHistory | None = None
        self._filter_scanning = False
        self._filter_force_pending = False
        self._page_buffer: PreparedPageSource | None = None
        self._prefetch_worker = None
        self._prefetched_edges = None
        self._fragment_budget = self.budget.max_items
        self.window: Window

    @property
    def fragment_views(self) -> tuple[TranscriptFragmentView, ...]:
        return tuple(child for page in self.pages for child in page.children)

    @property
    def _publication_current(self) -> bool:
        return self._committed and self.is_attached and not self._closing and not self._pruning

    def _require_publication(self) -> None:
        if not self._publication_current:
            raise _PublicationRetired

    @property
    def _follow_source_tail(self) -> bool:
        return self.window.follows_tail

    @property
    def _filter_before(self) -> TranscriptCursor | None:
        return self._filter_overlay.pages[0].page.before if self._filter_overlay is not None else None

    @property
    def _filter_has_older(self) -> bool:
        return self._filter_overlay.has_older if self._filter_overlay is not None else self.has_older

    def _report_coverage(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        if self._committed:
            self.post_message(self.Covered(page.events, self))

    def publish_committed(self) -> None:
        """Acquire live-row ownership only after a provisional mount is accepted."""
        self._committed = True
        self.post_message(self.Covered(tuple(self.coverage_events), self))
        self._scroll_changed()
        self._warm_pages()

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
        visible = self.screen._compositor.visible_widgets
        count = sum(child in visible for page in self.pages for child in page.children)
        return self.budget.item_limit(count)

    @property
    def fragment_count(self) -> int:
        return sum(page.stop - page.start for page in self.pages)

    @property
    def widget_limit(self) -> int:
        return self.budget.widget_limit(self.window.size.height)

    @property
    def widget_count(self) -> int:
        return sum(1 for _ in self.walk_children())

    def compose(self) -> ComposeResult:
        yield self.older
        for page in self.pages:
            page.visible_categories = self._selected_categories
            yield page
        yield self.newer

    def on_mount(self) -> None:
        from toad.widgets.conversation import Window
        self.window = self.query_ancestor(Window)
        self.window.histories.add(self)
        self._report_coverage(self.pages[0].page, self.pages[0].fragments)
        self._update_edges()
        self.watch(self.window, "scroll_y", self._scroll_changed, init=False)
        self.screen.screen_layout_refresh_signal.subscribe(self, self._layout_changed)
        self._scroll_changed()
        self._warm_pages()

    def on_unmount(self) -> None:
        self._generation += 1
        self.window.histories.discard(self)
        if self._page_buffer is not None:
            self._page_buffer.close()

    def _reader(self) -> PreparedPageSource:
        assert self.loader is not None
        reader = self._page_buffer
        if reader is None or reader.loader is not self.loader or reader.through != self.through:
            if reader is not None:
                reader.close()
            self._page_buffer = reader = TranscriptPageBuffer(
                self.loader, self.through, self.app.preparation,
            )
            self._prefetched_edges = None
        return reader

    def _warm_pages(self) -> None:
        if (self.loader is None or not self.is_mounted or not self._publication_current or not self.screen.is_current
                or not self._selected_categories):
            return
        reader = self._reader()
        edges = (self.pages[0].page.before if self.pages[0].page.has_older else None,
                 self.pages[-1].page.after if self.pages[-1].page.has_newer else None)
        if (edges == self._prefetched_edges
                or self._prefetch_worker is not None and not self._prefetch_worker.is_finished):
            return

        async def prepare() -> None:
            current = lambda: (self.is_attached and self.screen.is_current
                               and self._page_buffer is reader and not reader.closed
                               and bool(self._selected_categories))
            if await reader.prefetch(*edges, current) and current():
                self._prefetched_edges = edges

        self._prefetch_worker = self.run_worker(prepare(), group="history-lookahead", exit_on_error=False)

    def _layout_changed(self, _screen) -> None:
        # A scroll watcher may run before the compositor applies its new
        # positions. Recheck against the committed layout too, even if neither
        # the scroll value nor this history's size changes again.
        self._scroll_changed()
        self._warm_pages()

    def _update_edges(self) -> None:
        if not self._selected_categories:
            self.older.display = self.newer.display = False
            return
        self.older.display = self.has_older and self._filter_overlay is None
        self.newer.display = self.has_newer

    @property
    def _selected_categories(self) -> frozenset[type[MessageCategory]]:
        from toad.widgets.conversation import Contents, Conversation

        # A nested pager inherits the outer message's category, not the
        # synthetic role of its Markdown fragments.
        return (self.query_ancestor(Conversation).visible_categories
                if self.is_attached and isinstance(self.parent, Contents) else all_categories())

    @property
    def _filtered_source(self) -> bool:
        return self._selected_categories != all_categories()

    def filter_changed(self) -> None:
        """Retire only derived filtered rows when a visible-kind set changes."""
        self._generation += 1
        selected = self._selected_categories
        for page in self.pages:
            page.set_categories(selected)
        overlay = self._filter_overlay
        self._filter_overlay = None
        self._filter_force_pending = False
        if overlay is not None:
            overlay.display = False
            self.run_worker(self._remove_filtered_overlay(overlay), group="filter-reset")
        self._update_edges()
        self._scroll_changed()

    async def _remove_filtered_overlay(self, overlay: ProjectedTranscriptHistory) -> None:
        async with self.window.history_lock:
            if overlay.is_attached:
                await overlay.remove()
        if self.is_attached:
            self._scroll_changed()

    @property
    def _prefetch_distance(self) -> int:
        """Start background reads before the earlier edge enters the viewport."""
        return max(4, min(32, self.window.size.height // 2))

    def _scan_needed(self) -> bool:
        # Once mounted, the projected pager alone owns edge admission. Driving
        # it from the parent too can repeatedly schedule scans while it awaits.
        return (self._filter_overlay is None and bool(self._selected_categories)
                and self._filtered_source and self._filter_has_older
                and (self.window.max_scroll_y == 0
                     or self.window.scroll_y <= self._prefetch_distance))

    def _start_filtered_scan(self) -> None:
        if (self._selected_categories and self._filter_has_older
                and not self._filter_scanning and not self._advancing
                and (self._filter_overlay is None or not self._filter_overlay._loading)):
            self._filter_scanning = True
            self.run_worker(self._scan_filtered_older(), group="filtered-history")

    async def _scan_filtered_older(self) -> None:
        """Bootstrap a projected source; ordinary paging owns all later admission."""
        generation = self._generation
        admitted = False
        source = None

        def is_current() -> bool:
            return (generation == self._generation and self._publication_current
                    and self._filtered_source and bool(self._selected_categories))

        try:
            overlay = self._filter_overlay
            if overlay is not None:
                previous = set(overlay.fragment_views)
                if not overlay._loading and overlay.has_older:
                    overlay._loading = True
                    await overlay._load_page(True)
                admitted = bool(set(overlay.fragment_views) - previous)
                return
            else:
                page = self.pages[0]
                source = ProjectedTranscriptSource(
                    PreparedTranscriptPage(page.page, page.fragments[:page.start], 0),
                    self.loader, self.app.preparation, CategoryProjection(self._selected_categories),
                    upstream=self._reader() if self.loader is not None else None,
                )
                prepared = await source.boundary()
            if not is_current() or self.screen is not self.app.screen:
                return
            async with self.window.history_lock:
                if not is_current() or self.screen is not self.app.screen:
                    return
                visible = self.screen._compositor.visible_widgets
                viewport = self.window.content_region
                anchor = next((child for child in self.fragment_views
                               if child in visible and visible[child][0].overlaps(viewport)), None)
                overlay = self._filter_overlay = ProjectedTranscriptHistory(self, source, prepared)
                async with self.window.preserve_history(anchor):
                    await self.mount(overlay, before=self.pages[0])
                    if not is_current() or self._filter_overlay is not overlay:
                        raise _PublicationRetired
                    await overlay.admit_initial()
                    if not is_current() or self._filter_overlay is not overlay:
                        raise _PublicationRetired
                admitted = bool(overlay.fragment_views)
                self._update_edges()
                self._filter_force_pending = False
                if not admitted and overlay.has_older:
                    # Seed one real match when the boundary prefix is empty;
                    # later batches are owned by the child's normal edge path.
                    overlay._request_page(True)
        except _PublicationRetired:
            # filter_changed already hid/queued removal of the retired overlay.
            # Exception unwinding skips waiting for its obsolete anchor frame.
            return
        except (OSError, ValueError) as error:
            if is_current():
                self.notify(str(error), title="Filtered history", severity="error")
        finally:
            if source is not None and (self._filter_overlay is None or self._filter_overlay._reader() is not source):
                source.close()
            self._filter_scanning = False
            current_generation = generation == self._generation
            if current_generation and (admitted or not self._filter_has_older):
                self._filter_force_pending = False
            if (self.is_attached and self._filtered_source and not self._closing
                    and self.screen is self.app.screen):
                # A page containing no routed entries has no new widget/layout
                # event to drive the next step. Explicit clicks keep scanning
                # even if the overlay is currently outside the viewport.
                if current_generation and admitted and self._filter_has_older:
                    # Painted height, not pre-layout geometry, decides whether
                    # this result fills the viewport before reading more.
                    self.call_after_refresh(self._check_edges)
                elif self._filter_force_pending:
                    self.call_later(self._start_filtered_scan)
                elif self._scan_needed():
                    self.call_later(self._check_edges)

    class Covered(Message):
        """A saved page now owns these exact inbound wire identities."""

        def __init__(self, events: tuple[TranscriptEvent, ...],
                     history: TranscriptHistory | None = None) -> None:
            super().__init__()
            self.history = history
            self.sequences = incoming_sequences(events)

    def covers_incoming(self, sequence: int) -> bool:
        if not self._committed:
            return False
        if sequence in self.Covered(tuple(self.coverage_events)).sequences:
            return True
        return self._filter_overlay is not None and self._filter_overlay.covers_incoming(sequence)

    @property
    def committed_cursor(self) -> TranscriptCursor:
        return self.through

    @property
    def checkpoint_available(self) -> bool:
        return (self._publication_current and not self._loading and not self._advancing
                and not self._filter_scanning
                and (self._filter_overlay is None or self._filter_overlay.checkpoint_available))

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
            if not self.is_attached or not is_current():
                return False
            # Reject scans started with the old bound without discarding their
            # already accepted filtered overlay or its backward cursor.
            self.retain_committed(through)
            self._advancing = True
        try:
            while self.has_newer:
                if not is_current() or not self.is_attached:
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
        finally:
            self._advancing = False
            if self.is_attached:
                self._scroll_changed()

    async def update_live(self, page: TranscriptPage, *,
                          fragments: tuple[TranscriptFragment, ...] | None = None,
                          is_current: Callable[[], bool] | None = None) -> None:
        """Update a live message's bounded tail without remounting unchanged fragments."""
        self._generation += 1
        generation = self._generation
        window, view = self.window, self.pages[0]
        if fragments is None:
            fragments = await prepare_transcript_fragments(
                page.events, getattr(self.app, "render_processes", None),
            )
        async with window.history_lock:
            if (not self.is_attached or self.window is not window
                    or generation != self._generation or self.pages[0] is not view
                    or (is_current is not None and not is_current())):
                return
            self._saturated_widget_limit = 0
            if self._filter_overlay is not None:
                await self._filter_overlay.remove()
                self._filter_overlay = None
            view.page = page
            # Read current follow intent after preprocessing, never restore an
            # intent captured before the user could scroll during the await.
            await view.update_fragments(fragments, window.follows_tail)
            self._update_edges()

    def on_resize(self) -> None:
        if self.is_mounted:
            self._scroll_changed()

    def _scroll_changed(self, _y: float = 0) -> None:
        if not self._loading and not self._check_pending:
            self._check_pending = True
            self.call_after_refresh(self._check_edges)

    def _check_edges(self) -> None:
        self._check_pending = False
        if (self._loading or self._advancing or not self._publication_current
                or not self.screen.is_active or not self._selected_categories):
            return
        # Off-screen pagers must not ask for their region: after a scroll that
        # falls back to rebuilding geometry for the *whole* mounted transcript.
        # The layout signal also calls us once this pager enters the viewport.
        geometry = self.screen._compositor.visible_widgets.get(self)
        if geometry is None:
            return
        region, _clip = geometry
        viewport = self.window.content_region
        if not region.overlaps(viewport):
            return
        # Markdown parsing mounts its children asynchronously. Until that first
        # mount finishes, a page can look empty and trigger unnecessary reads
        # of many older pages. The committed child layout will recheck edges.
        if any(not child.is_mounted for child in self.walk_children()):
            return
        if self._follow_source_tail and self.has_newer:
            self._request_page(False)
            return
        if self._filtered_source:
            if self._scan_needed() or self._filter_force_pending:
                self._start_filtered_scan()
            return
        if (self.has_older and region.y >= viewport.y - self._prefetch_distance
               and not (self._follow_source_tail and (
                    self.fragment_count >= self.fragment_limit or len(self.pages) >= self.fragment_limit
                   or self.widget_count >= self.widget_limit
                   or self._saturated_widget_limit == self.widget_limit
              ))):
            self._request_page(True)
        elif self.has_newer and region.bottom <= viewport.bottom + 2:
            self._request_page(False)

    @on(JumpToLatest.Requested)
    def on_jump(self, event: JumpToLatest.Requested) -> None:
        event.stop()
        self.request_latest()

    @on(HistoryEdge.Requested)
    def on_earlier_history(self, event: HistoryEdge.Requested) -> None:
        event.stop()
        if self._filtered_source:
            if self._filter_overlay is not None:
                if self._filter_overlay.has_older:
                    self._filter_overlay._request_page(True)
            else:
                self._filter_force_pending = True
                self._start_filtered_scan()
        elif self.has_older and not self._loading:
            self._request_page(True)

    def request_latest(self) -> None:
        if not self._loading:
            self._loading = True
            self.run_worker(self._jump_latest())

    async def _jump_latest(self) -> None:
        self._generation += 1
        generation = self._generation
        window, loader = self.window, self.loader
        scroll_revision = window.scroll_revision
        try:
            if loader is None:
                page, fragments = self.pages[-1].page, self.pages[-1].fragments
            else:
                prepared = await self._reader().get(PageRequest(before=self.through))
                page, fragments = prepared.page, prepared.fragments
            async with window.history_lock:
                if (not self.is_attached or self.window is not window or self.loader is not loader
                        or generation != self._generation or window.scroll_revision != scroll_revision):
                    return
                self._saturated_widget_limit = 0
                await self.remove_children(list(self.pages))
                view = TranscriptPageView(page, fragments=fragments, batch_size=self.budget.admission_items)
                view.visible_categories = self._selected_categories
                self.pages = deque([view])
                await self.mount(view, before=self.newer)
                self._update_edges()
                self.call_after_refresh(self._anchor_latest, generation, scroll_revision)
        finally:
            self._loading = False
            if self.is_attached:
                self._scroll_changed()

    def _anchor_latest(self, generation: int, scroll_revision: int) -> None:
        if (self.is_attached and generation == self._generation
                and self.window.scroll_revision == scroll_revision):
            self.window.anchor()

    def _request_page(self, older: bool) -> None:
        if not self._loading:
            self._loading = True
            self.run_worker(self._load_page(older))

    async def _load_page(self, older: bool) -> None:
        window, loader = self.window, self.loader
        generation = self._generation
        scroll_intent = (window.scroll_revision, window.follows_tail, window.scroll_y)
        edge = self.pages[0] if older else self.pages[-1]
        edge_range = (edge.start, edge.stop)
        try:
            local = edge.start > 0 if older else edge.stop < len(edge.fragments)
            page = None
            fragments = None
            if not local:
                if loader is None:
                    return
                prepared = await self._reader().get(PageRequest(
                    before=edge.page.before if older else None,
                    after=edge.page.after if not older else None,
                ))
                page, fragments = prepared.page, prepared.fragments
            async with window.history_lock:
                if (not self._publication_current or self.window is not window or self.loader is not loader
                        or not self.screen.is_current
                        or generation != self._generation
                        or (self.pages[0] if older else self.pages[-1]) is not edge
                        or edge_range != (edge.start, edge.stop)
                        or scroll_intent != (window.scroll_revision, window.follows_tail, window.scroll_y)):
                    return
                visible = self.screen._compositor.visible_widgets
                viewport = self.window.content_region
                retained = [fragment for page in self.pages for fragment in page.children
                            if fragment in visible and visible[fragment][0].overlaps(viewport)]
                anchor = (retained[0 if older else -1] if retained else
                          edge.children[0 if older else -1] if edge.children else edge)
                position = HistoryAnchor.capture(anchor, self.window)
                # Visibility is already known by the compositor. Looking up
                # each off-screen fragment's region rebuilds the full map on
                # the scroll path immediately before mounting another page.
                protected = {anchor, *retained}
                # Native selection may extend beyond the viewport. Keep those
                # fragment owners until the reader releases the selection.
                endpoints = set(self.screen.selections)
                if self.screen.focused is not None:
                    endpoints.add(self.screen.focused)
                protected.update(protected_presentations(self.fragment_views, endpoints))
                # Filling a short tail is not a user scroll. Keep its anchor
                # active through layout, including a concurrent tab activation;
                # otherwise the first frame paints the old position and live
                # updates mistake the temporary release for scroll-up intent.
                if not position.follow_tail:
                    self.window.suspend_follow()
                async with self.window.preserve_history(anchor):
                    await self._extend_and_trim(edge, older, local, page, position, protected, fragments)
                    self._require_publication()
        except _PublicationRetired:
            return
        except (OSError, ValueError) as error:
            self.notify(str(error), title="History", severity="error")
        finally:
            self._loading = False
            if self.is_attached:
                self.window.check_follow()
                self._scroll_changed()

    async def _extend_and_trim(
        self, edge: TranscriptPageView, older: bool, local: bool,
        page: TranscriptPage | None, position: HistoryAnchor, protected: set[Widget],
        fragments: tuple[TranscriptFragment, ...] | None,
    ) -> None:
        # Serialize this native presentation, not every screen's paint. The
        # history anchor compensates each committed layout while mounts await.
        async with self.lock:
            previous_start = self.pages[0], self.pages[0].start
            overlay_visible = False
            if self._filter_overlay is not None:
                visible = self.screen._compositor.visible_widgets
                viewport = self.window.content_region
                overlay_visible = any(
                    child in visible and visible[child][0].overlaps(viewport)
                    for child in self._filter_overlay.fragment_views
                )
            if local:
                previous_children = set(edge.children)
                await edge.extend(older)
                self._require_publication()
                protected.update(child for child in edge.children if child not in previous_children)
            elif page is not None:
                assert fragments is not None
                view = TranscriptPageView(
                    page, newest=older, fragments=fragments, batch_size=self.budget.admission_items,
                )
                view.visible_categories = self._selected_categories
                await self.mount(view, before=edge if older else self.newer)
                self._require_publication()
                protected.update(view.children)
                protected.add(view)
                self._report_coverage(page, fragments)
                if older:
                    self.pages.appendleft(view)
                else:
                    self.pages.append(view)
            # Wire pages vary enormously in visible size. A fixed three
            # page cap can evict the tail before even filling one screen,
            # causing the edge loaders to ping-pong forever. Bound actual
            # fragments (and empty page overhead), not transport batches.
            self._fragment_budget = limit = self.budget.item_limit(len(set(self.fragment_views) & protected))
            excess = self.fragment_count - limit
            trim_older = self._follow_source_tail or not older
            while (excess > 0 or len(self.pages) > limit
                   or self.widget_count > self.widget_limit) and (self.fragment_count > 1 or len(self.pages) > 1):
                selected = None
                for side in (trim_older, not trim_older):
                    # A visible older projection protects the range between it
                    # and the canonical pages, just like a visible page anchor.
                    if side and overlay_visible:
                        continue
                    candidate = self.pages[0] if side else self.pages[-1]
                    if candidate in protected:
                        continue
                    children = list(candidate.children)
                    if not side:
                        children.reverse()
                    available = []
                    for child in children:
                        if child in protected:
                            break
                        available.append(child)
                    if available or not children:
                        selected = candidate, side, available
                        break
                if selected is None:
                    break
                evicted, side, available = selected
                count = evicted.stop - evicted.start
                remove_count = max(0, excess)
                over_widgets = self.widget_count - self.widget_limit
                if over_widgets > 0:
                    self._saturated_widget_limit = self.widget_limit
                    for index, child in enumerate(available, 1):
                        over_widgets -= 1 + sum(1 for _ in child.walk_children())
                        remove_count = max(remove_count, index)
                        if over_widgets <= 0:
                            break
                remove_count = min(remove_count, len(available), self.fragment_count - 1)
                if remove_count >= count and len(self.pages) > 1:
                    self.pages.popleft() if side else self.pages.pop()
                    await evicted.remove()
                    self._require_publication()
                    excess -= count
                else:
                    if not remove_count:
                        break
                    await evicted.trim(min(remove_count, count), older=side)
                    self._require_publication()
                    excess -= remove_count
            if (self._filter_overlay is not None and not overlay_visible
                    and previous_start != (self.pages[0], self.pages[0].start)):
                # Normal bounded eviction moved the canonical start. An older
                # overlay's cursor cannot skip the newly omitted interval.
                await self._filter_overlay.remove()
                self._filter_overlay = None
                self._generation += 1
            self._update_edges()


class ProjectedTranscriptHistory(TranscriptHistory):
    """A source projection with the ordinary pager's admission and eviction policy."""

    def __init__(self, owner: TranscriptHistory, source: ProjectedTranscriptSource,
                 prepared: PreparedTranscriptPage) -> None:
        self._projection_owner = ref(owner)
        super().__init__(prepared.page, source.loader, fragments=prepared.fragments, budget=owner.budget)
        self._page_buffer = source
        # Finish the container's native mount before awaiting row admission.
        # A slow/held row batch must not strand the page's own message pump in
        # Compose, where input-settlement barriers would wait on its startup.
        self.pages[0].stop = self.pages[0].start
        self._loading = True
        self.add_class("filtered-history-results")

    async def admit_initial(self) -> None:
        try:
            self._require_publication()
            await self.pages[0].extend(False)
            self._require_publication()
            self._update_edges()
        finally:
            self._loading = False
            if self._publication_current:
                self._scroll_changed()

    @property
    def _publication_current(self) -> bool:
        owner = self._projection_owner()
        return (super()._publication_current and owner is not None
                and owner._publication_current and owner._filter_overlay is self)

    @property
    def _selected_categories(self) -> frozenset[type[MessageCategory]]:
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

    def _report_coverage(self, page: TranscriptPage, fragments: tuple[TranscriptFragment, ...]) -> None:
        owner = self._projection_owner()
        if owner is not None and owner._filter_overlay is self:
            owner._report_coverage(replace(page, events=tuple(
                event for fragment in fragments for event in fragment.events
            )), fragments)
