"""Bounded, cursor-paged saved history; all transcript interpretation is model-owned."""

from collections import deque
from dataclasses import replace
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
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
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from toad.widgets.history_anchor import HistoryAnchor
from toad.widgets.message_filter import (
    ALL_CATEGORIES, CategorizedBlock, MessageCategory, event_category, is_routed_event, keep_events,
)
from toad.widgets.transcript_fragments import (
    TranscriptFragment, prepare_transcript_fragments, transcript_fragments,
)

if TYPE_CHECKING:
    from toad.widgets.conversation import Window


def transcript_blocks(events: tuple[TranscriptEvent, ...], *, fragment: bool = False,
                      show_divider: bool = True) -> list[Widget]:
    blocks: list[Widget] = []
    tools: dict[str, protocol.ToolCall] = {}
    for event in events:
        kind, text = event.kind, event.text
        if kind == "user":
            if event.routing is not None and event.routing.requests:
                from toad.widgets.incoming_message import IncomingMessage
                message = event.routing.requests[0]
                blocks.append(IncomingMessage(
                    message.sender, text, message.target, show_header=show_divider,
                ))
            else:
                blocks.append(UserInput(text, show_divider=show_divider))
        elif kind in {"assistant", "notice", "sent"}:
            blocks.append(AgentResponse(
                text, route=event.routing.reply if event.routing else None,
                category=event_category(event), paginate=not fragment,
                show_divider=show_divider,
            ))
        elif kind == "thinking":
            blocks.append(AgentThought(text, paginate=not fragment))
        elif kind in {"tool_start", "tool_end"}:
            tool_id = event.tool_call_id
            if tool_id not in tools:
                tools[tool_id] = {
                    "sessionUpdate": "tool_call", "toolCallId": tool_id,
                    "title": event.tool_name or "Tool", "status": "completed",
                    "kind": tool_kind(event.tool_name),
                }
                blocks.append(ToolCall(tools[tool_id], id=encode_tool_call_id(tool_id)))
            if kind == "tool_start":
                tools[tool_id]["rawInput"] = event.raw_input
            else:
                tools[tool_id]["status"] = "completed" if event.ok else "failed"
                tools[tool_id]["content"] = tool_result_content(tool_id, text, event.diff)
    return blocks


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


class TranscriptFragmentView(VerticalGroup):
    def __init__(self, fragment: TranscriptFragment):
        super().__init__()
        self.fragment = fragment
        self._message_category = (event_category(fragment.events[0]) if fragment.events
                                  else MessageCategory.OTHER)
        self.add_class(f"-message-{self._message_category.value}")
        self.set_class(not any(is_routed_event(event) for event in fragment.events), "-unrouted")

    def compose(self) -> ComposeResult:
        # A semantic fragment may be one oversized paragraph, list, or fence.
        # It is already a page leaf: re-paging it would recursively remount the
        # same indivisible block forever without producing visible Markdown.
        yield from transcript_blocks(
            self.fragment.events, fragment=True, show_divider=not self.fragment.continuation,
        )

    async def update_fragment(self, fragment: TranscriptFragment) -> None:
        """Keep a live text leaf and its routing controls when only text changed.

        A tool/result or routing change still requires normal recomposition.
        Updating Markdown itself preserves the outer scene, subscriptions and
        styles instead of destroying and reconstructing the entire fragment.
        """
        old_events, new_events = self.fragment.events, fragment.events
        self.fragment = fragment
        category = event_category(new_events[0]) if new_events else MessageCategory.OTHER
        if category != self._message_category:
            self.remove_class(f"-message-{self._message_category.value}")
            self.add_class(f"-message-{category.value}")
            self._message_category = category
        self.set_class(not any(is_routed_event(event) for event in new_events), "-unrouted")
        if (len(old_events) == len(new_events) == 1
                and old_events[0].kind in {"assistant", "thinking", "notice", "sent"}
                and replace(old_events[0], text=new_events[0].text) == new_events[0]
                and len(self.children) == 1):
            leaf = self.children[0]
            if isinstance(leaf, (AgentResponse, AgentThought)):
                await leaf.update(new_events[0].text)
                return
        await self.recompose()


class TranscriptPageView(VerticalGroup):
    BATCH = 4

    def __init__(self, page: TranscriptPage, *, newest: bool = True,
                 fragments: tuple[TranscriptFragment, ...] | None = None):
        super().__init__()
        self.page = page
        self.fragments = transcript_fragments(page.events) if fragments is None else fragments
        self.start = max(0, len(self.fragments) - self.BATCH) if newest else 0
        self.stop = min(len(self.fragments), self.start + self.BATCH)

    def compose(self) -> ComposeResult:
        for fragment in self.fragments[self.start:self.stop]:
            yield TranscriptFragmentView(fragment)

    async def extend(self, older: bool) -> None:
        start = max(0, self.start - self.BATCH) if older else self.stop
        stop = self.start if older else min(len(self.fragments), self.stop + self.BATCH)
        widgets = [TranscriptFragmentView(fragment) for fragment in self.fragments[start:stop]]
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
        start = max(0, stop - self.BATCH) if follow else min(self.start, stop)
        for index, child in previous.items():
            if not start <= index < stop:
                await child.remove()
        for index in range(start, stop):
            child = previous.get(index)
            if child is None:
                await self.mount(TranscriptFragmentView(fragments[index]))
            elif child.fragment != fragments[index]:
                await child.update_fragment(fragments[index])
        self.start, self.stop = start, stop


class TranscriptHistory(CategorizedBlock, VerticalGroup):
    MAX_FRAGMENTS = 24

    @property
    def message_category(self) -> None:
        return None

    def __init__(self, page: TranscriptPage, loader: Callable[..., Awaitable[TranscriptPage]] | None = None,
                 *, fragments: tuple[TranscriptFragment, ...] | None = None):
        super().__init__()
        self.pages = deque([TranscriptPageView(page, fragments=fragments)])
        self.loader = loader
        self.through = page.after
        self.older = HistoryEdge("↑ Earlier history loads as you scroll")
        self.older.tooltip = "Click or press Enter to load earlier history, including in In/out only mode"
        self.newer = JumpToLatest("↓ Jump to latest")
        self._loading = False
        self._check_pending = False
        self._saturated_widget_limit = 0
        self._generation = 0
        self._filter_overlay: VerticalGroup | None = None
        self._filter_before: TranscriptCursor | None = None
        self._filter_has_older = True
        self._filter_scanning = False
        self._filter_force_pending = False
        self.window: Window

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
        return max(self.MAX_FRAGMENTS, self.window.size.height * 2)

    @property
    def fragment_count(self) -> int:
        return sum(page.stop - page.start for page in self.pages)

    @property
    def widget_limit(self) -> int:
        return max(300, self.window.size.height * 10)

    @property
    def widget_count(self) -> int:
        return sum(1 for _ in self.walk_children())

    def compose(self) -> ComposeResult:
        yield self.older
        yield from self.pages
        yield self.newer

    def on_mount(self) -> None:
        from toad.widgets.conversation import Window
        self.window = self.query_ancestor(Window)
        self.window.histories.add(self)
        self._update_edges()
        self.watch(self.window, "scroll_y", self._scroll_changed, init=False)
        self.screen.screen_layout_refresh_signal.subscribe(self, self._layout_changed)
        self._scroll_changed()

    def on_unmount(self) -> None:
        self._generation += 1
        self.window.histories.discard(self)

    def _layout_changed(self, _screen) -> None:
        # A scroll watcher may run before the compositor applies its new
        # positions. Recheck against the committed layout too, even if neither
        # the scroll value nor this history's size changes again.
        self._scroll_changed()

    def _update_edges(self) -> None:
        self.older.display = (self._filter_has_older if self._filtered_source and
                              self._filter_before is not None else self.has_older)
        self.newer.display = self.has_newer

    @property
    def _filtered_source(self) -> bool:
        from toad.widgets.conversation import Contents, Conversation

        return (self.is_attached and isinstance(self.parent, Contents)
                and self.query_ancestor(Conversation).visible_categories != ALL_CATEGORIES)

    def filter_changed(self) -> None:
        """Retire only derived filtered rows when a visible-kind set changes."""
        self._generation += 1
        overlay = self._filter_overlay
        self._filter_overlay = None
        self._filter_before = None
        self._filter_has_older = True
        self._filter_force_pending = False
        if overlay is not None:
            overlay.display = False
            self.run_worker(self._remove_filtered_overlay(overlay), group="filter-reset")
        self._update_edges()
        self._scroll_changed()

    async def _remove_filtered_overlay(self, overlay: VerticalGroup) -> None:
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
        return (self._filtered_source and self._filter_has_older
                and (self.window.max_scroll_y == 0
                     or self.window.scroll_y <= self._prefetch_distance))

    def _start_filtered_scan(self) -> None:
        if self._filter_has_older and not self._filter_scanning:
            self._filter_scanning = True
            self.run_worker(self._scan_filtered_older(), group="filtered-history")

    async def _scan_filtered_older(self) -> None:
        """Project routed older records without mounting non-routed widgets."""
        from toad.widgets.transcript_fragments import prepare_transcript_fragments

        generation = self._generation
        from toad.widgets.conversation import Conversation

        selected = self.query_ancestor(Conversation).visible_categories
        before = self._filter_before
        fragments: tuple[TranscriptFragment, ...] = ()
        try:
            if before is None:
                page = self.pages[0]
                fragments = tuple(fragment for fragment in page.fragments[:page.start]
                                  if keep_events(fragment.events, selected))
                next_before = page.page.before
                has_older = page.page.has_older
            else:
                if self.loader is None:
                    self._filter_has_older = False
                    return
                page = await self.loader(before=before, through=self.through)
                if (page.before.session_file != before.session_file
                        or page.before.offset >= before.offset and page.has_older):
                    raise ValueError("Earlier routed history made no cursor progress")
                events = tuple(event for event in page.events if event_category(event) in selected)
                fragments = await prepare_transcript_fragments(
                    events, getattr(self.app, "render_processes", None)) if events else ()
                next_before, has_older = page.before, page.has_older
            if (generation != self._generation or not self.is_attached
                    or not self._filtered_source or self.screen is not self.app.screen):
                return
            async with self.window.history_lock:
                if generation != self._generation or not self._filtered_source:
                    return
                if fragments:
                    visible = self.screen._compositor.visible_widgets
                    viewport = self.window.content_region
                    retained = [child for page in self.pages for child in page.children
                                if child in visible and visible[child][0].overlaps(viewport)]
                    if self._filter_overlay is not None:
                        retained.extend(child for child in self._filter_overlay.children
                                        if child in visible and visible[child][0].overlaps(viewport))
                    anchor = retained[0] if retained else None

                    async def insert() -> None:
                        if self._filter_overlay is None:
                            self._filter_overlay = VerticalGroup(classes="filtered-history-results")
                            await self.mount(self._filter_overlay, before=self.pages[0])
                        nodes = [TranscriptFragmentView(fragment) for fragment in fragments]
                        await self._filter_overlay.mount(
                            *nodes, before=self._filter_overlay.children[0]
                            if self._filter_overlay.children else None)

                    if anchor is None:
                        await insert()
                    else:
                        async with self.window.preserve_history(anchor):
                            await insert()
                self._filter_before, self._filter_has_older = next_before, has_older
                self._update_edges()
        except (OSError, ValueError) as error:
            self._filter_has_older = False
            self.notify(str(error), title="Filtered history", severity="error")
        finally:
            self._filter_scanning = False
            if fragments or not self._filter_has_older:
                self._filter_force_pending = False
            if self.is_attached and self._filtered_source:
                # A page containing no routed entries has no new widget/layout
                # event to drive the next step. Explicit clicks keep scanning
                # even if the overlay is currently outside the viewport.
                if fragments and self._filter_has_older:
                    # Painted height, not pre-layout geometry, decides whether
                    # this result fills the viewport before reading more.
                    self.call_after_refresh(self._check_edges)
                elif self._filter_force_pending:
                    self.call_later(self._start_filtered_scan)
                elif self._scan_needed():
                    self.call_later(self._check_edges)

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
                self._filter_before = None
                self._filter_has_older = True
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
        if self._loading or not self.is_attached or not self.screen.is_active:
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
        if self.window.follows_tail and self.has_newer:
            self._request_page(False)
            return
        if self._filtered_source:
            if self._scan_needed() or self._filter_force_pending:
                self._start_filtered_scan()
            return
        if (self.has_older and region.y >= viewport.y - self._prefetch_distance
               and not (self.window.follows_tail and (
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
                page = await loader(before=self.through, through=self.through)
                fragments = await prepare_transcript_fragments(
                    page.events, getattr(self.app, "render_processes", None),
                )
            async with window.history_lock:
                if (not self.is_attached or self.window is not window or self.loader is not loader
                        or generation != self._generation or window.scroll_revision != scroll_revision):
                    return
                self._saturated_widget_limit = 0
                await self.remove_children(list(self.pages))
                view = TranscriptPageView(page, fragments=fragments)
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
                page = await loader(
                    before=edge.page.before if older else None,
                    after=edge.page.after if not older else None,
                    through=self.through,
                )
                fragments = await prepare_transcript_fragments(
                    page.events, getattr(self.app, "render_processes", None),
                )
            async with window.history_lock:
                if (not self.is_attached or self.window is not window or self.loader is not loader
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
                # Filling a short tail is not a user scroll. Keep its anchor
                # active through layout, including a concurrent tab activation;
                # otherwise the first frame paints the old position and live
                # updates mistake the temporary release for scroll-up intent.
                if not position.follow_tail:
                    self.window.suspend_follow()
                async with self.window.preserve_history(anchor):
                    await self._extend_and_trim(edge, older, local, page, position, protected, fragments)
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
        with self.app.batch_update():
            if local:
                await edge.extend(older)
            elif page is not None:
                assert fragments is not None
                view = TranscriptPageView(page, newest=older, fragments=fragments)
                await self.mount(view, before=edge if older else self.newer)
                if older:
                    self.pages.appendleft(view)
                else:
                    self.pages.append(view)
            # Wire pages vary enormously in visible size. A fixed three
            # page cap can evict the tail before even filling one screen,
            # causing the edge loaders to ping-pong forever. Bound actual
            # fragments (and empty page overhead), not transport batches.
            limit = self.fragment_limit
            excess = self.fragment_count - limit
            trim_older = position.follow_tail or not older
            while (excess > 0 or len(self.pages) > limit
                   or self.widget_count > self.widget_limit) and self.fragment_count > 1:
                selected = None
                for side in (trim_older, not trim_older):
                    candidate = self.pages[0] if side else self.pages[-1]
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
                    excess -= count
                else:
                    if not remove_count:
                        break
                    await evicted.trim(min(remove_count, count), older=side)
                    excess -= remove_count
            self._update_edges()
