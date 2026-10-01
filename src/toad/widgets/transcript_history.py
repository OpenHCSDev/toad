"""Bounded, cursor-paged saved history; all transcript interpretation is model-owned."""

from __future__ import annotations
from toad.block_navigation import ConversationBlock

from toad.widgets.message_filter import OtherCategory

import asyncio
from collections import deque
from dataclasses import dataclass, replace
from functools import partial
from collections.abc import Awaitable, Callable, Iterator
from typing import TYPE_CHECKING
from weakref import ref

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent, ContextTranscript, UserTranscript, IncomingTranscript, AgentTextTranscript, SentTranscript,
    ThinkingTranscript, ToolTranscript, ToolStartTranscript, ToolEndTranscript,
)
from agent_comms.tool_results import tool_result_content
from agent_comms.native_tools import NativeTool
from textual import events, on
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from toad.transcript_filter import FilterSnapshot, TranscriptFilter
from toad.transcript_state import TranscriptState, LiveTranscript, ProvisionalTranscript
from toad.transcript_source_preparation import TranscriptSourcePreparation
from acp import schema as protocol
from toad.acp.status import ToolCallStatus
from pydantic import TypeAdapter
from toad.acp.encode_tool_call_id import encode_tool_call_id
from toad.transcript_preparation import (
    CategoryProjection, CommittedInterval, PageRequest, PreparedPageSource, PreparedTranscriptPage,
    ProjectedTranscriptSource, incoming_sequences,
)
from toad.widgets.agent_response import AgentResponse, ResponseDelivery
from toad.widgets.agent_thought import AgentThought
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from toad.widgets.message_divider import AgentActivityDivider, MessageClock
from toad.widgets.presentation_window import PresentationBudget, protected_presentations
from toad.widgets.viewport_body import MeasuredViewportBody, ViewportBody
from toad.work_preparation import retained_bytes
from toad.widgets.committed_presentation import CommittedHistory, TranscriptCoverage, TranscriptInputClaim
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
        self.blocks.append(UserInput(event.text, claim=TranscriptInputClaim(event),
                                     show_divider=self.show_divider,
                                     clock=MessageClock.recorded(event.timestamp)))

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript):
        from toad.widgets.incoming_message import IncomingMessage
        self.blocks.append(IncomingMessage(event, show_header=self.show_divider))

    @handles(SentTranscript)
    def sent(self, event: SentTranscript):
        from toad.widgets.outgoing_message import OutgoingMessage
        self.blocks.append(OutgoingMessage(event, show_header=self.show_divider))

    @handles(AgentTextTranscript)
    def agent(self, event: AgentTextTranscript):
        self.blocks.append(AgentResponse(
            event.text, delivery=ResponseDelivery.from_route(event.routing.reply if event.routing else None),
            category=event_category(event), paginate=not self.fragment,
            show_divider=self.show_divider, clock=MessageClock.recorded(event.timestamp),
        ))

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript):
        self.blocks.append(AgentThought(event.text, paginate=not self.fragment))

    def tool(self, event: ToolTranscript) -> protocol.ToolCall:
        tool_id = event.tool_call_id
        if tool_id not in self.tools:
            self.tools[tool_id] = protocol.ToolCall(
                tool_call_id=tool_id, title=event.tool_name or 'Tool', status='completed',
                kind=NativeTool.start(tool_id, event.tool_name, {}).kind)

            self.blocks.append(ToolCall(ToolCallStatus.from_acp(self.tools[tool_id]), id=encode_tool_call_id(tool_id)))
        return self.tools[tool_id]

    @handles(ToolStartTranscript)
    def tool_start(self, event: ToolStartTranscript):
        self.tool(event).raw_input = event.raw_input

    @handles(ToolEndTranscript)
    def tool_end(self, event: ToolEndTranscript):
        tool = self.tool(event)
        tool.status = "completed" if event.ok else "failed"
        tool.content = TypeAdapter(protocol.ToolCall.model_fields["content"].annotation).validate_python(tool_result_content(event.tool_call_id, event.text, event.diff), strict=True)


def transcript_blocks(events: tuple[TranscriptEvent, ...], *, fragment: bool = False,
                      show_divider: bool = True) -> list[Widget]:
    consumer = TranscriptBlockConsumer(fragment=fragment, show_divider=show_divider)
    for event in events:
        consumer.dispatch_sync(event)
    # All native tool events in this page are assembled before UI admission.
    # Capture the final typed state once, so a failed end cannot leave a completed badge.
    for block in consumer.blocks:
        if isinstance(block, ToolCall):
            block.set_reactive(ToolCall.tool_call, ToolCallStatus.from_acp(consumer.tools[block.tool_call.call.tool_call_id]))
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


class TranscriptFragmentView(MeasuredViewportBody, CategorizedBlock, VerticalGroup):
    CACHE_HEIGHT_INDEPENDENT_BOX = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True

    def __init__(self, fragment: TranscriptFragment, selected=None):
        super().__init__()
        self.fragment = fragment
        self._retained_bytes = retained_bytes(fragment)
        self._body_viewport = None
        self._message_category = (event_category(fragment.events[0]) if fragment.events
                                  else OtherCategory)
        self.add_class(f"-message-{self._message_category.declared_name}")
        self.set_class(not any(event.routed for event in fragment.events), "-unrouted")
        self.set_categories(all_categories() if selected is None else selected)

    def on_mount(self) -> None:
        from toad.widgets.history_anchor import HistoryWindow
        window = self.query_ancestor(HistoryWindow)
        self._body_viewport = window.document_viewport
        self._body_viewport.register(self)

    def on_unmount(self) -> None:
        if self._body_viewport is not None:
            self._body_viewport.discard(self)

    @property
    def retained_source_bytes(self) -> int:
        return self._retained_bytes

    async def retire_body(self) -> bool:
        if not self.body_ready or self._body_measurement is None:
            return False
        # Pruning replaces the whole materialization, including hidden bodies.
        # Join their original readiness here, not on every viewport frame.
        if any(not child.body_ready for child in self.walk_children()
               if isinstance(child, ViewportBody)):
            return False
        self.retire_measurement()
        await self.remove_children()
        self.refresh(layout=True)
        return True

    async def restore_body(self) -> None:
        if self._body_dormant:
            self._body_restoring = True
            try:
                await self.recompose()
                self._body_dormant = False
                self.refresh(layout=True)
            finally:
                self._body_restoring = False

    async def prepare_body(self) -> None:
        from toad.render_tasks import TranscriptBodyPreparation
        preparation = TranscriptBodyPreparation(
            self.app.render_processes, self.app.native_ansi_color, self.app.current_theme.dark,
        )
        for event in self.fragment.events:
            await preparation.dispatch(event)

    @property
    def message_category(self) -> type[MessageCategory]:
        return self._message_category

    def set_categories(self, selected: frozenset[type[MessageCategory]]) -> None:
        if getattr(self, "selected_categories", None) == selected:
            return
        self.selected_categories = selected
        apply_block_filter(self, selected)

    def compose(self) -> ComposeResult:
        # A semantic fragment may be one oversized paragraph, list, or fence.
        # It is already a page leaf: re-paging it would recursively remount the
        # same indivisible block forever without producing visible Markdown.
        if self.fragment.starts_agent_activity and not self.fragment.continuation:
            yield AgentActivityDivider(self._message_category, clock=MessageClock.recorded(self.fragment.events[0].timestamp))
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
        self._retained_bytes = retained_bytes(fragment)
        category = event_category(new_events[0]) if new_events else OtherCategory
        if category != self._message_category:
            self.remove_class(f"-message-{self._message_category.declared_name}")
            self.add_class(f"-message-{category.declared_name}")
            self._message_category = category
            apply_block_filter(self, self.selected_categories)
        self.set_class(not any(event.routed for event in new_events), "-unrouted")
        if (len(old_events) == len(new_events) == 1
                and old_events[0].merge(new_events[0]) is not None
                and previous_fragment.starts_agent_activity == fragment.starts_agent_activity
                and previous_fragment.continuation == fragment.continuation
                and (len(self.children) == 1 or
                     (len(self.children) == 2 and isinstance(self.children[0], AgentActivityDivider)))):
            leaf = self.children[-1]
            if isinstance(leaf, (AgentResponse, AgentThought)):
                await leaf.update(new_events[0].text)
                return
        await self.recompose()


@dataclass(frozen=True)
class TranscriptPageAdmission:
    """A measured page's admitted range, without retaining its rich widgets."""

    interval: CommittedInterval
    start: int
    stop: int


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

    def _body(self, fragment: TranscriptFragment) -> TranscriptFragmentView:
        return TranscriptFragmentView(fragment, self.visible_categories)

    def compose(self) -> ComposeResult:
        for fragment in self.fragments[self.start:self.stop]:
            yield self._body(fragment)

    def capture_admission(self) -> TranscriptPageAdmission:
        return TranscriptPageAdmission(
            CommittedInterval(self.page.before, self.page.after), self.start, self.stop,
        )

    def restore_admission(self, admission: TranscriptPageAdmission) -> None:
        # Positions refer to this immutable native interval, not to whatever
        # newer snapshot happened to be published during an inactive turn.
        if admission.interval != CommittedInterval(self.page.before, self.page.after):
            return
        self.start, self.stop = admission.start, admission.stop

    def set_categories(self, selected: frozenset[type[MessageCategory]]) -> None:
        self.visible_categories = selected
        for child in self.children:
            child.set_categories(selected)

    async def prepare_adjacent(self, preparation, demand, count: int, keep_going) -> None:
        """Warm unmounted source leaves beside this page's actual admission."""
        fragments = demand.neighbors(self.fragments, self.start, self.stop, count)
        await preparation.prepare_fragments(fragments, keep_going, batch_size=self.batch_size)

    async def extend(self, older: bool) -> None:
        start = max(0, self.start - self.batch_size) if older else self.stop
        stop = self.start if older else min(len(self.fragments), self.stop + self.batch_size)
        before = self.children[0] if older and self.children else None
        for index in range(start, stop):
            body = self._body(self.fragments[index])
            await self.mount(body, before=before)
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
                body = self._body(fragments[index])
                await self.mount(body)
            elif child.fragment != fragments[index]:
                await child.update_fragment(fragments[index])
        self.start, self.stop = start, stop


class TranscriptHistory(TranscriptSourcePreparation, ConversationBlock, CommittedHistory, CategorizedBlock, VerticalGroup):
    CACHE_HEIGHT_INDEPENDENT_BOX = True
    CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT = True
    MAX_FRAGMENTS = 24

    @property
    def message_category(self) -> None:
        return None

    def __init__(self, page: TranscriptPage, loader: Callable[..., Awaitable[TranscriptPage]] | None = None,
                  *, fragments: tuple[TranscriptFragment, ...] | None = None,
                  budget: PresentationBudget | None = None, committed: bool = True):
        super().__init__(source_state=LiveTranscript() if committed else ProvisionalTranscript(),
                         loader=loader, through=page.after)
        self.budget = budget or PresentationBudget(
            max_items=self.MAX_FRAGMENTS, admission_items=TranscriptPageView.BATCH,
        )
        self.pages = deque([TranscriptPageView(
            page, fragments=fragments, batch_size=self.budget.admission_items,
        )])
        self.older = HistoryEdge("↑ Earlier history loads as you scroll")
        self.older.tooltip = "Click or press Enter to load earlier history, including in In/out only mode"
        self.newer = JumpToLatest("↓ Jump to latest")
        self._check_pending = False
        self._saturated_widget_limit = 0
        self.filter = TranscriptFilter(self)
        self._fragment_budget = self.budget.max_items
        self.window: Window

    @property
    def fragment_views(self) -> tuple[TranscriptFragmentView, ...]:
        return tuple(child for page in self.pages for child in page.children)

    def _require_publication(self) -> None:
        if not self.state.accepts_publication:
            raise _PublicationRetired

    @property
    def filter_publication_available(self) -> bool:
        if not self.state.accepts_publication:
            return False
        return self.screen.is_current

    def invalidate_projection(self) -> None:
        self._generation += 1

    def filter_snapshot(self) -> FilterSnapshot:
        return FilterSnapshot(self._generation, self.selected_categories,
                              self.window, self.loader, self.screen)

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
            # The native page admission still owns its frame fence. Transfer
            # identity-backed rows before releasing it; a queued message can
            # otherwise paint saved and live resources together.
            # Standalone saved viewers have no live transcript to transfer.
            # Resolve custody from native ancestry, not a second owner field.
            for ancestor in self.ancestors:
                if isinstance(ancestor, Conversation):
                    await ancestor.transcript.covered(TranscriptCoverage(page.events, self))
                    break

    def publish_committed(self) -> None:
        """Acquire live-row ownership only after a provisional mount is accepted."""
        self._source_state = self._source_state.publish()
        self.post_message(TranscriptCoverage(tuple(self.coverage_events), self))
        self._scroll_changed()
        self.prepare_scroll()

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
        sequence = self.fragment_views
        indexes = [index for index, child in enumerate(sequence) if child in visible]
        if not indexes:
            return self.budget.item_limit(0)
        runway = self.window.document_viewport.budget.runway(
            sequence, min(indexes), max(indexes) + 1, self.window.size.height,
        )
        return max(self.budget.item_limit(len(indexes)), len(indexes) + len(runway))

    @property
    def fragment_count(self) -> int:
        return sum(page.stop - page.start for page in self.pages)

    @property
    def widget_limit(self) -> int:
        return self.budget.widget_limit(self.window.size.height)

    @property
    def widget_count(self) -> int:
        # Body descendants have one native cost owner. Headers, pages, filters
        # and pending native mounts remain part of this history's actual tree.
        pending = list(self.children)
        count = 0
        while pending:
            child = pending.pop()
            if isinstance(child, ViewportBody):
                count += child.materialized_widget_count
            else:
                count += 1
                pending.extend(child.children)
        return count

    @property
    def retained_source_bytes(self) -> int:
        return sum(node.retained_source_bytes for node in self.walk_children()
                   if isinstance(node, ViewportBody))

    def compose(self) -> ComposeResult:
        yield self.older
        for page in self.pages:
            page.visible_categories = self.selected_categories
            yield page
        yield self.newer

    async def on_mount(self) -> None:
        from toad.widgets.conversation import Window
        self.window = self.query_ancestor(Window)
        await self._finish_mount()

    async def _finish_mount(self) -> None:
        self.window.histories.add(self)
        await self._report_coverage(self.pages[0].page, self.pages[0].fragments)
        self._update_edges()
        self.watch(self.window, "scroll_y", self._scroll_changed, init=False)
        self.screen.screen_layout_refresh_signal.subscribe(self, self._layout_changed)
        self._scroll_changed()
        self.prepare_scroll()

    def on_unmount(self) -> None:
        self._generation += 1
        self._prefetch_intent = None
        self.window.histories.discard(self)
        if self._page_buffer is not None:
            self._page_buffer.close()




    def _layout_changed(self, _screen) -> None:
        # A scroll watcher may run before the compositor applies its new
        # positions. Recheck against the committed layout too, even if neither
        # the scroll value nor this history's size changes again.
        self._scroll_changed()
        self.prepare_scroll()

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
    def checkpoint_available(self) -> bool:
        return self.state.accepts_source_work and self.filter.checkpoint_available

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
            async with window.preserve_history(None):
                self._saturated_widget_limit = 0
                await self.filter.remove()
                view.page = page
                # Read current follow intent after preprocessing, never restore an
                # intent captured before the user could scroll during the await.
                await view.update_fragments(fragments, window.follows_tail)
                self._update_edges()

    def on_resize(self) -> None:
        if self.is_mounted:
            self._scroll_changed()

    def _scroll_changed(self, _y: float = 0) -> None:
        if self.state.accepts_source_work and not self._check_pending:
            self._check_pending = True
            self.call_after_refresh(self._check_edges)

    def _check_edges(self) -> None:
        self._check_pending = False
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
        if self.filter.active:
            self.filter.check_edges()
            return
        if (self.has_older and region.y >= viewport.y - self.prefetch_distance
               and not (self._follow_source_tail and (
                    self.fragment_count >= self.fragment_limit or len(self.pages) >= self.fragment_limit
                   or self.widget_count >= self.widget_limit
                   or self._saturated_widget_limit == self.widget_limit
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

    def request_latest(self) -> None:
        self.window.document_viewport.destination()
        if self._prefetch_worker is not None:
            self._prefetch_worker.cancel()
        self._prefetch_intent = None
        self.state.request_latest(self)

    async def _jump_latest(self) -> None:
        self._generation += 1
        generation = self._generation
        window, loader = self.window, self.loader
        destination_admission = window.document_viewport.lookahead.admission(self.budget, window.size.height)
        scroll_revision = window.scroll_revision
        if loader is None:
            page, fragments = self.pages[-1].page, self.pages[-1].fragments
        else:
            prepared = await self._reader().get(PageRequest(before=self.through))
            page, fragments = prepared.page, prepared.fragments
        async with window.history_lock:
            if (not self.is_attached or self.window is not window or self.loader is not loader
                    or generation != self._generation or window.scroll_revision != scroll_revision):
                return
            async with window.preserve_history(None):
                self._saturated_widget_limit = 0
                await self.remove_children(list(self.pages))
                view = TranscriptPageView(
                    page, fragments=fragments,
                    batch_size=destination_admission,
                )
                view.visible_categories = self.selected_categories

                self.pages = deque([view])
                await self.mount(view, before=self.newer)
                self._update_edges()
                self.call_after_refresh(self._anchor_latest, generation, scroll_revision)

    def _anchor_latest(self, generation: int, scroll_revision: int) -> None:
        if (self.is_attached and generation == self._generation
                and self.window.scroll_revision == scroll_revision):
            self.window.anchor()

    def _request_page(self, older: bool) -> None:
        if self.state.accepts_source_work:
            self.reserve_source_work().schedule(self, partial(self._load_page, older))

    async def _load_page(self, older: bool) -> None:
        window, loader = self.window, self.loader
        generation = self._generation
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
                if (not self.state.accepts_publication or self.window is not window or self.loader is not loader
                        or not self.screen.is_current
                        or generation != self._generation
                        or (self.pages[0] if older else self.pages[-1]) is not edge
                        or edge_range != (edge.start, edge.stop)):
                    return
                # Source admission survives reader movement. Choose the current
                # visible record after preparation, including a reversed reader.
                visible = self.screen._compositor.visible_widgets
                viewport = self.window.content_region
                retained = [fragment for page in self.pages for fragment in page.children
                            if fragment in visible and visible[fragment][0].overlaps(viewport)]
                anchor = (retained[0 if older else -1] if retained else
                          edge.children[0 if older else -1] if edge.children else edge)
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
                if not self.window.follows_tail:
                    self.window.release_anchor()
                async with self.window.preserve_history(anchor):
                    await self._extend_and_trim(edge, older, local, page, protected, fragments)
                    self._require_publication()
        except _PublicationRetired:
            return
        except (OSError, ValueError) as error:
            self.notify(str(error), title="History", severity="error")
        finally:
            if self.state.accepts_publication:
                self.window.check_follow()

    async def _extend_and_trim(
        self, edge: TranscriptPageView, older: bool, local: bool,
        page: TranscriptPage | None, protected: set[Widget],
        fragments: tuple[TranscriptFragment, ...] | None,
    ) -> None:
        # HistoryWindow owns the mutation's native frame publication and
        # compensated layout; this lock serializes the page's admission.
        async with self.lock:
            previous_start = self.pages[0], self.pages[0].start
            overlay_visible = self.filter.projection_visible()
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
                view.visible_categories = self.selected_categories
                await self.mount(view, before=edge if older else self.newer)
                self._require_publication()
                protected.update(view.children)
                protected.add(view)
                await self._report_coverage(page, fragments)
                if older:
                    self.pages.appendleft(view)
                else:
                    self.pages.append(view)
            # Wire pages vary enormously in visible size. A fixed three
            # page cap can evict the tail before even filling one screen,
            # causing the edge loaders to ping-pong forever. Bound actual
            # fragments (and empty page overhead), not transport batches.
            self._fragment_budget = limit = max(
                self.budget.item_limit(len(set(self.fragment_views) & protected)),
                self._visible_fragment_budget(),
            )
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
                        over_widgets -= child.materialized_widget_count
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
            await self.filter.canonical_moved(previous_start, overlay_visible)
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
        self.reserve_source_work()
        self.add_class("filtered-history-results")

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
        await self.pages[0].extend(False)
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
