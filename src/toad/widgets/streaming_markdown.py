"""A bounded Markdown view owns exactly one updater, only while streaming."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from contextlib import asynccontextmanager

from markdown_it import MarkdownIt
from markdown_it.token import Token

from textual.await_complete import AwaitComplete
from textual.widgets.markdown import MarkdownStream
from textual.widget import Widget
from textual.app import ComposeResult

from toad.widgets.prepared_markdown import PreparedContentRange, PreparedConversationMarkdown
from toad.widgets.committed_presentation import SnapshotPresentation
from toad.conversation_markdown import _ThreadLocalPathParser
from toad.render_tasks import MarkdownPartsTask, MarkdownRenderTask
from toad.markdown_preparation import PreparedMarkdownPart
from toad.widgets.transcript_fragments import RenderBudget
from toad.widgets.presentation_window import PresentationBudget, protected_presentations
from toad.widgets.viewport_body import MaterializingBody

class StreamingMarkdown(PreparedContentRange, SnapshotPresentation, PreparedConversationMarkdown):

    def __init__(self, markdown: str | None = None, *, paginate: bool = True,
                 prefix: tuple[Widget, ...] = (), **kwargs) -> None:
        self._paginate = paginate
        self._prefix = prefix
        super().__init__(markdown, **kwargs)
        self._stream: MarkdownStream | None = None
        self.budget = PresentationBudget()
        self._content_lock = asyncio.Lock()
        self._content_generation = 0
        self._pending_source: str | None = None
        self._needs_full_markdown_update = False

    def compose(self) -> ComposeResult:
        yield from self._prefix

    def _body(self, fragment: PreparedMarkdownPart) -> PreparedConversationMarkdown:
        return PreparedConversationMarkdown(fragment.text, classes="-message-fragment")

    @property
    def retained_source_bytes(self) -> int:
        return sum(part.retained_bytes for part in self.fragments)

    def capture_admission(self):
        return self._content_generation, self.start, self.stop

    @property
    def has_newer_source(self) -> bool:
        return self.stop < len(self.fragments)

    async def _prepare_parts(self, parts, current: Callable[[], bool]) -> bool:
        for first in range(0, len(parts), self.batch_size):
            if not current():
                return False
            await asyncio.gather(*(self.app.render_processes.prepare(MarkdownRenderTask(
                part.text, self.app.native_ansi_color, self.app.current_theme.dark,
            )) for part in parts[first:first + self.batch_size]))
        return current()

    async def materialize_native_body(self) -> None:
        await self._update_content(self.source, append=False)

    @asynccontextmanager
    async def retirement_custody(self):
        async with self._content_lock:
            async with super().retirement_custody() as can_commit:
                # append_fragment may acquire its stream while preparation
                # awaits, before its first content mutation changes the body.
                yield can_commit and self._stream is None

    def reconstructible_children(self) -> tuple[Widget, ...]:
        if self._stream is not None or self._content_lock.locked():
            return ()
        return self.fragment_views or super().reconstructible_children()

    def retire_body_resources(self) -> None:
        self._fragment_views = ()
        super().retire_body_resources()

    def update(self, markdown: str) -> AwaitComplete:
        return self.publish_body(partial(self._update_content, markdown, append=False))

    def append(self, markdown: str) -> AwaitComplete:
        return self.publish_body(partial(self._update_content, markdown, append=True))

    async def _parse_tokens(
        self, parser: MarkdownIt | _ThreadLocalPathParser, markdown: str, *, use_thread: bool,
    ) -> list[Token] | None:
        generation = self._content_generation
        tokens = await super()._parse_tokens(parser, markdown, use_thread=use_thread)
        if tokens is None or self._closing or generation != self._content_generation:
            self._needs_full_markdown_update = True
            return None
        return tokens

    async def _update_content(self, text: str, *, append: bool) -> None:
        if self._closing:
            return
        self._content_generation += 1
        generation = self._content_generation
        previous_source = self.source if self._pending_source is None else self._pending_source
        source = previous_source + text if append else text
        self._pending_source = source
        parent = self.parent

        def is_current() -> bool:
            return (not self._closing and self.is_attached and self.parent is parent
                    and generation == self._content_generation)

        try:
            await self._publish_content(source, text, append, is_current)
        except asyncio.CancelledError:
            if generation == self._content_generation:
                self._content_generation += 1
                self._pending_source = self.source
            raise

    async def _publish_content(self, source: str, text: str, append: bool,
                               is_current: Callable[[], bool]) -> None:
        async with self._content_lock:
            if not is_current():
                return
            if self.body_dormant:
                self._needs_full_markdown_update = True
            fragments = (await self.app.render_processes.submit(MarkdownPartsTask(source))
                         if self._paginate and not RenderBudget().fits(source) else ())
            if not is_current():
                return
            if len(fragments) <= 1:
                if self.fragments:
                    await self.remove_children(self.fragment_views)
                    self.fragments, self._fragment_views = (), ()
                    self.start = self.stop = 0
                if append and self.source + text == source and not self._needs_full_markdown_update:
                    await self._append_body_source(text)
                else:
                    await self._update_body_source(source)
                if is_current():
                    self._needs_full_markdown_update = False
                return
            from toad.widgets.history_anchor import HistoryWindow

            window = self.query_ancestor(HistoryWindow)
            if self.fragments and source == self.source:
                selected = slice(self.start, self.stop)
            elif self.fragments:
                selected = self.update_slice(fragments, window.follows_tail)
            else:
                selected = self.initial_slice(fragments, self.batch_size, True)
            if not await self._prepare_parts(fragments[selected], is_current):
                return
            previous = {self.start + index: child
                        for index, child in enumerate(self.fragment_views)}
            for index, child in previous.items():
                if not is_current():
                    return
                if selected.start <= index < selected.stop and child.source != fragments[index].text:
                    await child.update(fragments[index].text)
            async with window.preserve_history(None, root=self):
                if not is_current():
                    return
                if not self.fragments:
                    await self.remove_children(child for child in self.children if child not in self._prefix)
                if not await self.replace_range(
                    fragments, selected, previous, is_current, prefix=self._prefix,
                ):
                    return
                self._markdown = source
                self.loading = False

    async def prepare_visible_source(self) -> bool:
        if (not self.fragments or not self.is_attached or self._closing
                or self.body_dormant or self._content_lock.locked()
                or isinstance(self._body_measurement, MaterializingBody)
                or not self.screen.is_current):
            return False
        geometry = self.screen._compositor.visible_widgets.get(self)
        if geometry is None:
            return False
        from toad.widgets.history_anchor import HistoryWindow

        window = self.query_ancestor(HistoryWindow)
        region, _clip = geometry
        distance = window.document_viewport.lookahead.ahead_rows(window.size.height)
        admission = self.capture_admission()
        if (window.follows_tail and window.document_viewport.source_tail is self
                and self.stop < len(self.fragments)):
            await self.publish_body(partial(self._admit_range, False, latest=True))
        elif self.start > 0 and region.y >= window.content_region.y - distance:
            await self.publish_body(partial(self._admit_range, True))
        elif self.stop < len(self.fragments) and region.bottom <= window.content_region.bottom + distance:
            await self.publish_body(partial(self._admit_range, False))
        return self.capture_admission() != admission

    async def _admit_range(self, older: bool, *, latest: bool = False) -> bool:
        from toad.widgets.history_anchor import HistoryWindow

        async with self._content_lock:
            window = self.query_ancestor(HistoryWindow)
            admission = self.capture_admission()
            parent = self.parent
            demand = window.document_viewport.lookahead.demand
            def current():
                return (self.is_attached and not self._closing and self.parent is parent
                        and self.capture_admission() == admission and self.screen.is_current
                        and window.document_viewport.lookahead.accepts(demand)
                        and window.document_viewport.requires_body(self)
                        and (not latest or (window.follows_tail
                                            and window.document_viewport.source_tail is self)))
            selected = (self.initial_slice(self.fragments, self.batch_size, True) if latest
                        else self.extension_slice(older))
            if not await self._prepare_parts(self.fragments[selected], current):
                return False
            async with window.preserve_history(None, root=self):
                if not current():
                    return False
                if latest:
                    previous = {self.start + index: child
                                for index, child in enumerate(self.fragment_views)}
                    if not await self.replace_range(
                        self.fragments, selected, previous, current, prefix=self._prefix,
                    ):
                        return False
                elif not await self.extend(older, current):
                    return False
                visible = self.screen._compositor.visible_widgets
                protected = protected_presentations(self.fragment_views, self.screen._interaction_widgets())
                protected.update(child for child in self.fragment_views if child in visible)
                limit = self.budget.item_limit(len(protected))
                excess = len(self.fragment_views) - limit
                ordered = self.fragment_views if not older else tuple(reversed(self.fragment_views))
                removable = 0
                for child in ordered:
                    if removable == max(0, excess) or child in protected:
                        break
                    removable += 1
                if removable:
                    self.trim(removable, older=not older)
                return True

    @property
    def stream(self) -> MarkdownStream:
        if self._stream is None:
            self._stream = self.get_stream(self)
        return self._stream

    async def append_fragment(self, fragment: str) -> None:
        self.loading = False
        await self.stream.write(fragment)

    async def finish_stream(self) -> None:
        """Flush pending fragments and release the updater's widget reference."""
        stream, self._stream = self._stream, None
        if stream is not None:
            await stream.stop()
        # MarkdownStream shields an append already in progress from cancellation.
        async with self._content_lock:
            pass

    async def on_unmount(self) -> None:
        self._content_generation += 1
        await self.finish_stream()
