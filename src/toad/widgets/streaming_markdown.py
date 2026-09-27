"""A bounded Markdown view owns exactly one updater, only while streaming."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt
from markdown_it.token import Token

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from textual.await_complete import AwaitComplete
from textual.widgets.markdown import MarkdownStream
from textual.widget import Widget
from textual.app import ComposeResult

from toad.widgets.prepared_markdown import PreparedConversationMarkdown
from toad.widgets.committed_presentation import SnapshotPresentation
from toad.conversation_markdown import _ThreadLocalPathParser
from toad.widgets.transcript_fragments import prepare_transcript_fragments

if TYPE_CHECKING:
    from toad.widgets.transcript_history import TranscriptHistory


class StreamingMarkdown(SnapshotPresentation, PreparedConversationMarkdown):
    RICH_TEXT_LIMIT = 1200
    TRANSCRIPT_ROLE = "assistant"

    def __init__(self, markdown: str | None = None, *, paginate: bool = True,
                 prefix: tuple[Widget, ...] = (), **kwargs) -> None:
        self._paginate = paginate
        self._prefix = prefix
        super().__init__(markdown, **kwargs)
        self._stream: MarkdownStream | None = None
        self._paged: TranscriptHistory | None = None
        self._dormant_page_range: tuple[int, int] | None = None
        self._content_lock = asyncio.Lock()
        self._content_generation = 0
        self._pending_source: str | None = None
        self._needs_full_markdown_update = False
        self._closing = False

    def compose(self) -> ComposeResult:
        yield from self._prefix

    async def retire_body(self) -> bool:
        if self._stream is not None or self._content_lock.locked():
            return False
        async with self._content_lock:
            if self._paged is not None:
                if (self._body_dormant or self._body_measurement is None or self.loading
                        or not self.is_attached or self._body_viewport is None
                        or self in self._body_viewport.protected()):
                    return False
                # Synthetic message paging has one immutable source page. Keep
                # its admitted source range, never the retired pager widgets.
                page = self._paged.pages[0]
                self._dormant_page_range = page.start, page.stop
                self._body_dormant = True
                pager, self._paged = self._paged, None
                await pager.remove()
                self._prepared_fences.clear()
                self.refresh(layout=True)
                return True
            return await super().retire_body()

    def update(self, markdown: str) -> AwaitComplete:
        return AwaitComplete(self._update_content(markdown, append=False))

    def append(self, markdown: str) -> AwaitComplete:
        return AwaitComplete(self._update_content(markdown, append=True))

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
        from toad.widgets.transcript_history import TranscriptHistory

        async with self._content_lock:
            if not is_current():
                return
            if source != self.source:
                self._dormant_page_range = None
            if self.body_dormant:
                # Streaming can resume on a previously cold message. Rebuild
                # its complete source before allowing the incremental tail path.
                if not self._body_restoring:
                    self._body_dormant = False
                self._needs_full_markdown_update = True
            if not self._paginate or (self._paged is None and len(source) <= self.RICH_TEXT_LIMIT):
                if append and self.source + text == source and not self._needs_full_markdown_update:
                    await super().append(text)
                else:
                    await super().update(source)
                if is_current():
                    self._needs_full_markdown_update = False
                return
            cursor = TranscriptCursor("", 0)
            page = TranscriptPage(
                (TranscriptEvent(self.TRANSCRIPT_ROLE, source),),
                cursor, cursor, False, False,
            )
            fragments = await prepare_transcript_fragments(
                page.events, getattr(self.app, "render_processes", None),
            )
            # The outer message owns its divider; inner render fragments only
            # supply Markdown content while the live message is paged.
            fragments = tuple(replace(fragment, continuation=True) for fragment in fragments)
            if not is_current():
                return
            self._markdown = source
            self.loading = False
            if self._paged is None:
                await self.remove_children(child for child in self.children if child not in self._prefix)
                if not is_current():
                    return
                self._paged = TranscriptHistory(page, fragments=fragments)
                if self._dormant_page_range is not None:
                    start, stop = self._dormant_page_range
                    self._paged.pages[0].start = start
                    self._paged.pages[0].stop = stop
                    self._dormant_page_range = None
                await self.mount(self._paged)
            else:
                await self._paged.update_live(page, fragments=fragments, is_current=is_current)

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
        self._closing = True
        self._content_generation += 1
        self._cancel_preparation()
        await self.finish_stream()
