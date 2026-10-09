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
from textual.widgets import Markdown
from toad.widgets.viewport_body import ChildBody, MaterializingBody, PreparedDocumentBody

from toad.widgets.prepared_markdown import PreparedConversationMarkdown
from toad.widgets.committed_presentation import SnapshotPresentation
from toad.conversation_markdown import ConversationMarkdown, _ThreadLocalPathParser
from toad.render_tasks import MarkdownPartsTask, MarkdownSyntaxRenderTask
from toad.markdown_preparation import PreparedContentRange, PreparedMarkdownPart
from toad.widgets.presentation_window import PresentationBudget, protected_presentations

class StreamingMarkdown(SnapshotPresentation, PreparedConversationMarkdown):

    def __init__(self, markdown: str | None = None, *, paginate: bool = True,
                 prefix: tuple[Widget, ...] = (),
                 prepared_content: PreparedContentRange | None = None, **kwargs) -> None:
        self._paginate = paginate
        self.prepared_content = prepared_content if prepared_content is not None else PreparedContentRange()
        if prepared_content is not None:
            # The retained source owns its accepted request. Event metadata
            # does not replace it while its original publication is pending.
            markdown = prepared_content.requested_text
        self._fragment_views = ()
        self._prefix = prefix
        super().__init__(markdown, **kwargs)
        self._stream: MarkdownStream | None = None
        self.budget = PresentationBudget()
        self._content_lock = asyncio.Lock()
        self._needs_full_markdown_update = False

    @property
    def _pending_source(self):
        return self.prepared_content.requested_text

    @_pending_source.setter
    def _pending_source(self, markdown):
        self.prepared_content.request_text(markdown)

    def compose(self) -> ComposeResult:
        yield from self._prefix
        if self.prepared_content.input_ready:
            yield from self.prepared_content.compose(self)

    @property
    def fragments(self):
        return self.prepared_content.fragments

    @property
    def start(self):
        return self.prepared_content.start

    @property
    def stop(self):
        return self.prepared_content.stop

    @property
    def batch_size(self):
        return self.prepared_content.batch_size

    @property
    def fragment_views(self):
        return self._fragment_views

    def _retain_fragment_source(self, fragment, body):
        return body.prepared_source

    def retain_sources(self):
        self.prepared_content.retain_sources(self)
        return self.prepared_content

    def retain_transcript_source(self, fragment):
        fragment.prepared_content = self.retain_sources()

    def _initialize_document(self, markdown):
        if self.partitionable_syntax:
            self.publish_body(self.materialize_native_body).call_when_ready(self)
            return AwaitComplete.nothing()
        return super()._initialize_document(markdown)

    def live_body_measurement(self, width=0, rows=0, widgets=1):
        # Partitioned conversation syntax owns a range of original documents.
        # An arbitrary parser still owns its original native scene contract.
        if self.partitionable_syntax:
            return ChildBody(width, rows, widgets)
        return super().live_body_measurement(width, rows, widgets)

    def _body(self, fragment, index, *, source=None) -> PreparedConversationMarkdown:
        if source is None:
            source = self.prepared_content.acquired(index, syntax=fragment)
        return (fragment if source is None else source).body(
            PreparedConversationMarkdown, content_owner=self.prepared_content,
            classes="-message-fragment")

    @property
    def retained_source_bytes(self) -> int:
        return self.prepared_content.retained_source_bytes + super().retained_source_bytes

    def capture_admission(self):
        return self.prepared_content.capture_admission()

    def _heading_owners(self):
        for part_index, child in enumerate(self.fragment_views, self.start):
            for level, title, block_id in child.table_of_contents:
                yield (level, title, f"part-{part_index}-{block_id}"), child, block_id

    @property
    def table_of_contents(self):
        if not self.partitionable_syntax:
            return super().table_of_contents
        return [entry for entry, _child, _block_id in self._heading_owners()]

    def goto_anchor(self, anchor: str) -> bool:
        if not self.partitionable_syntax:
            return super().goto_anchor(anchor)
        headings = tuple(self._heading_owners())
        selected = self.anchor_id_for([entry for entry, _child, _block_id in headings], anchor)
        for entry, child, block_id in headings:
            if entry[2] != selected:
                continue
            measurement = child._body_measurement
            if isinstance(measurement, PreparedDocumentBody):
                if not measurement.ready(child):
                    return False
                for heading in measurement.paint.headings:
                    if heading.entry[2] == block_id and heading.placement is not None:
                        child.scroll_to_region(heading.placement.region, top=True)
                        return True
                return False
            for block in child.children:
                if block.id == block_id:
                    block.scroll_visible(top=True)
                    return True
        return False

    def on_markdown_table_of_contents_updated(self, event: Markdown.TableOfContentsUpdated):
        if event.markdown in self.fragment_views:
            event.stop()
            self.post_message(Markdown.TableOfContentsUpdated(self, self.table_of_contents))

    @property
    def has_newer_source(self) -> bool:
        return self.stop < len(self.fragments)

    async def materialize_native_body(self) -> None | bool:
        content = self.prepared_content
        generation = content.generation
        if self.partitionable_syntax and content.input_ready:
            from toad.widgets.history_anchor import HistoryWindow

            window = self.query_ancestor(HistoryWindow)
            current = lambda: (self.is_attached and not self._closing
                               and self.prepared_content is content and content.generation == generation)
            previous = {self.start + index: child for index, child in enumerate(self.fragment_views)}
            # Mount/sort/prune belong to the original document transaction.
            # Child source joins happen in BodyMeasurement after it releases.
            async with window.preserve_history(None, root=self):
                if not await content.replace_range(
                    self, self.fragments, slice(self.start, self.stop), previous, current, prefix=self._prefix,
                ):
                    return False
                self._markdown = content.requested_text
            self.loading = False
            return True
        return await self._update_content(content, generation, self.acquired_source(content.requested_text),
                                         "", append=False)

    async def materialize_interactive_body(self):
        # This source range owns real prefix/disclosure widgets. Its document
        # children own native controls; do not flatten those roles into paint.
        await self.materialize_body()
        for child in self.fragment_views:
            await child.materialize_interactive_body()

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
        # A whole-source request owns a fresh range even when text is equal.
        # Existing controls keep their native lifetime, but cannot certify the
        # new source. Append retains unchanged earlier part acquisitions.
        previous = self.prepared_content
        self.prepared_content = PreparedContentRange(batch_size=previous.batch_size)
        # Native predecessor controls retain their actual slot coordinates.
        # The new source has no acquired inputs or suppliers until delivery.
        self.prepared_content.admission = previous.admission
        source = self._request_source(markdown, append=False)
        content = self.prepared_content
        return self.publish_body(partial(self._update_content, content, content.generation,
                                         self.acquired_source(source), markdown, append=False))

    def append(self, markdown: str) -> AwaitComplete:
        source = self._request_source(markdown, append=True)
        content = self.prepared_content
        return self.publish_body(partial(self._update_content, content, content.generation,
                                         self.acquired_source(source), markdown, append=True))

    async def _parse_tokens(
        self, parser: MarkdownIt | _ThreadLocalPathParser, markdown: str | PreparedMarkdownPart, *, use_thread: bool,
    ) -> list[Token] | None:
        content = self.prepared_content
        generation = content.generation
        tokens = await super()._parse_tokens(parser, markdown, use_thread=use_thread)
        if (tokens is None or self._closing or self.prepared_content is not content
                or generation != content.generation):
            self._needs_full_markdown_update = True
            return None
        return tokens

    async def _update_content(self, content: PreparedContentRange, generation: int,
                              source: str | PreparedMarkdownPart, text: str, *, append: bool) -> None | bool:
        if self._closing:
            return False
        parent = self.parent

        def is_current() -> bool:
            return (not self._closing and self.is_attached and self.parent is parent
                    and self.prepared_content is content and generation == content.generation)

        # Cancellation revokes this publisher, not the accepted source request.
        return await self._publish_content(source, text, append, is_current)

    async def _publish_content(self, acquired: str | PreparedMarkdownPart, text: str, append: bool,
                               is_current: Callable[[], bool]) -> None | bool:
        source = acquired.text if isinstance(acquired, PreparedMarkdownPart) else acquired
        async with self._content_lock:
            if not is_current():
                return False
            # MaterializingBody is dormant while publishing, even when its
            # previous native roots remain usable. Append needs reconstruction
            # only after those roots have actually been retired.
            if not super().reconstructible_children():
                self._needs_full_markdown_update = True
            fragments = ()
            prepared = None
            if self.partitionable_syntax:
                if self._paginate:
                    prepared = await self.app.render_processes.submit(MarkdownPartsTask(acquired))
                else:
                    part = (acquired if isinstance(acquired, PreparedMarkdownPart) else
                            await self.app.render_processes.submit(MarkdownSyntaxRenderTask(acquired)))
                    prepared = PreparedContentRange((part,), source=part)
                    prepared.fragment_bytes = part.retained_bytes
                fragments = prepared.fragments
            if not is_current():
                return False
            if not self.partitionable_syntax:
                if self.fragments:
                    await self.remove_children(self.fragment_views)
                    self.prepared_content.fragments, self._fragment_views = (), ()
                    self.prepared_content.select_admission(slice(0, 0))
                    self.prepared_content.fragment_bytes = 0
                    self._needs_full_markdown_update = True
                # Custom grammar/factory behavior belongs to this original
                # native owner, including its block callbacks and root prefix.
                # It cannot be replaced by conversation-syntax source parts.
                if (append and self.source + text == source
                        and not self._needs_full_markdown_update):
                    await ConversationMarkdown.append(self, text)
                else:
                    await ConversationMarkdown.update(self, source)
                if not is_current():
                    return False
                self._needs_full_markdown_update = False
                # Keep native completion as a None publication result; only
                # this source owner's revocation refuses its admission.
                return
            from toad.widgets.history_anchor import HistoryWindow

            window = self.query_ancestor(HistoryWindow)
            if self.fragments and source == self.source:
                selected = slice(self.start, self.stop)
            elif self.fragments:
                selected = self.prepared_content.update_slice(fragments, window.follows_tail)
            else:
                selected = self.prepared_content.initial_slice(fragments, self.batch_size, True)
            if self.fragment_views:
                self.prepared_content.retain_sources(self)
            if not await prepared.prepare(self.app.render_processes, self.app.native_ansi_color,
                                          self.app.current_theme.dark, selected=selected, current=is_current,
                                          previous=self.prepared_content):
                return False
            previous = {self.start + index: child
                        for index, child in enumerate(self.fragment_views)}
            for index, child in previous.items():
                if not is_current():
                    return False
                if (selected.start <= index < selected.stop
                        and (child._content_owner is not self.prepared_content
                             or child._markdown_part != fragments[index])):
                    self.prepared_content.revoke_source(index)
                    await child.update_part(fragments[index], content_owner=self.prepared_content)
            async with window.preserve_history(None, root=self):
                if not is_current():
                    return False
                if not self.fragment_views:
                    await self.remove_children(child for child in self.children if child not in self._prefix)
                if not await self.prepared_content.replace_range(
                    self, fragments, selected, previous, is_current, prefix=self._prefix, acquired=prepared,
                ):
                    return False
                self._markdown = source
                self.loading = False
                return True

    async def prepare_visible_source(self) -> bool:
        if (not self.prepared_content.input_ready or not self.fragments or not self.is_attached or self._closing
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
            selected = (self.prepared_content.initial_slice(self.fragments, self.batch_size, True) if latest
                        else self.prepared_content.extension_slice(older))
            if not await self.prepared_content.prepare(
                self.app.render_processes, self.app.native_ansi_color, self.app.current_theme.dark,
                selected=selected, current=current,
            ):
                return False
            async with window.preserve_history(None, root=self):
                if not current():
                    return False
                if latest:
                    previous = {self.start + index: child
                                for index, child in enumerate(self.fragment_views)}
                    if not await self.prepared_content.replace_range(
                        self, self.fragments, selected, previous, current, prefix=self._prefix,
                    ):
                        return False
                elif not await self.prepared_content.extend(self, older, current, prefix=self._prefix):
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
                    self.prepared_content.trim(self, removable, older=not older)
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
        await self.finish_stream()
