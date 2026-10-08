"""Use the app-owned CPU pool for heavy conversation Markdown preparation."""

import asyncio
from contextlib import ExitStack, asynccontextmanager
from collections.abc import Callable
from functools import partial
from typing import cast

from markdown_it import MarkdownIt
from markdown_it.token import Token


from textual.content import Content
from textual.app import ComposeResult
from textual.worker import WorkerCancelled
from textual.await_complete import AwaitComplete
from textual.widget import Widget
from textual.widgets import Label
from textual.widgets._markdown import Markdown, MarkdownBlock

from toad.app import ToadApp
from toad.conversation_markdown import ConversationCodeFence, ConversationMarkdown, _ThreadLocalPathParser
from toad.markdown_preparation import PreparedMarkdown, PreparedMarkdownPart
from toad.block_content import MarkdownBlockContent
from toad.render_tasks import MarkdownRenderTask
from toad.widgets.viewport_body import MeasuredViewportBody
from toad.widgets.worker_static import WorkerStatic


class PreparedContentRange:
    """Bound native source parts without giving them transcript identity.

    Transcript pages and individual Markdown messages share native admission,
    not cursors, coverage, categories or source acquisition. Each owner supplies
    its original admission identity and constructs its own part widgets.
    Mount commits membership only. BodyMeasurement owns content publication;
    the viewport's frame receipt admits paint and the next measured page edge.
    Joining child writers here would hold their parent's mutation fence while
    those writers need that same window to publish their content.
    """

    BATCH = 4

    def __init__(self, *args, fragments=(), newest: bool = True,
                 batch_size: int = BATCH, **kwargs):
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        self.batch_size = batch_size
        self.fragments = fragments
        selected = self.initial_slice(fragments, batch_size, newest)
        self.start, self.stop = selected.start, selected.stop
        self._fragment_views = ()
        super().__init__(*args, **kwargs)

    @staticmethod
    def initial_slice(fragments, batch_size: int, newest: bool) -> slice:
        start = max(0, len(fragments) - batch_size) if newest else 0
        return slice(start, min(len(fragments), start + batch_size))

    def _body(self, fragment):
        raise NotImplementedError

    def compose(self):
        self._fragment_views = tuple(self._body(fragment)
                                     for fragment in self.fragments[self.start:self.stop])
        yield from self._fragment_views

    @property
    def fragment_views(self):
        return self._fragment_views

    def on_unmount(self) -> None:
        self._fragment_views = ()

    def capture_admission(self):
        raise NotImplementedError

    def extension_slice(self, older: bool) -> slice:
        return (slice(max(0, self.start - self.batch_size), self.start) if older
                else slice(self.stop, min(len(self.fragments), self.stop + self.batch_size)))

    def update_slice(self, fragments, follow: bool) -> slice:
        if follow:
            return self.initial_slice(fragments, self.batch_size, True)
        stop = min(self.stop, len(fragments))
        return slice(min(self.start, stop), stop)

    async def extend(self, older: bool, current: Callable[[], bool], *, prefix=()) -> bool:
        admission = self.capture_admission()
        extension = self.extension_slice(older)
        selected = slice(extension.start if older else self.start,
                         self.stop if older else extension.stop)
        previous = {self.start + index: child for index, child in enumerate(self.fragment_views)}
        return await self.replace_range(
            self.fragments, selected, previous,
            lambda: current() and self.capture_admission() == admission,
            prefix=prefix,
        )

    async def replace_range(self, fragments, selected, previous, current, *, prefix=()) -> bool:
        """Publish ordered native parts inside their owner's source custody."""
        ordered = []
        added = []
        with ExitStack() as acquisition:
            acquisition.callback(lambda: self.remove_children(added))
            # Source demand may span a viewport. Native construction/mount
            # remains a bounded burst, including after worker preparation.
            # Keep the original admission until every batch has joined.
            for first in range(selected.start, selected.stop, self.BATCH):
                if not current():
                    return False
                batch = []
                for index in range(first, min(selected.stop, first + self.BATCH)):
                    if index in previous:
                        child = previous[index]
                    else:
                        child = self._body(fragments[index])
                        added.append(child)
                        batch.append(child)
                    ordered.append(child)
                if batch:
                    await self.mount_all(batch)
                    if not current():
                        return False
            if not current():
                return False
            self.fragments, self._fragment_views = fragments, tuple(ordered)
            self.start, self.stop = selected.start, selected.stop
            desired = (*prefix, *ordered)
            if tuple(self.children) != desired:
                rank = {child: index for index, child in enumerate(desired)}
                self.sort_children(key=lambda child: rank.get(child, len(rank)))
            self.remove_children(tuple(child for child in previous.values() if child not in ordered))
            acquisition.pop_all()
        return True

    def trim(self, count: int, *, older: bool) -> None:
        bodies = self.fragment_views
        boundary = count if older else len(bodies) - count
        retired = bodies[:boundary] if older else bodies[boundary:]
        self._fragment_views = bodies[boundary:] if older else bodies[:boundary]
        if older:
            self.start += count
        else:
            self.stop -= count
        self.remove_children(retired)


class PreparedMarkdownContent(WorkerStatic):
    """Native blocks keep token/link custody; WorkerStatic owns their wrapping."""

    @asynccontextmanager
    async def preparation_publication(self, *, layout: bool):
        from toad.widgets.history_anchor import HistoryWindow

        window = next((ancestor for ancestor in self.ancestors
                       if isinstance(ancestor, HistoryWindow)), None)
        if layout and window is not None:
            # WorkerStatic installs detached paint and invalidates extent; it
            # does not mount, remove or reorder native children. The document
            # owns those mutations. Borrow its reader compensation without
            # reacquiring that document's native tree fence on a child worker.
            async with window.preserve_reader(window.reader_anchor(self)):
                yield
        else:
            async with super().preparation_publication(layout=layout):
                yield


class PreparedParagraph(ConversationMarkdown.BLOCKS["paragraph_open"], PreparedMarkdownContent):
    pass


class PreparedH1(ConversationMarkdown.BLOCKS["h1"], PreparedMarkdownContent):
    pass


class PreparedH2(ConversationMarkdown.BLOCKS["h2"], PreparedMarkdownContent):
    pass


class PreparedH3(ConversationMarkdown.BLOCKS["h3"], PreparedMarkdownContent):
    pass


class PreparedH4(ConversationMarkdown.BLOCKS["h4"], PreparedMarkdownContent):
    pass


class PreparedH5(ConversationMarkdown.BLOCKS["h5"], PreparedMarkdownContent):
    pass


class PreparedH6(ConversationMarkdown.BLOCKS["h6"], PreparedMarkdownContent):
    pass


class PreparedConversationMarkdown(MarkdownBlockContent, MeasuredViewportBody, ConversationMarkdown):
    DEFAULT_CSS = """
    PreparedConversationMarkdown.-message-fragment {
        min-height: 1;
        padding: 0;
        margin: 0;
        layout: stream;
    }
    """

    BLOCKS = {
        **ConversationMarkdown.BLOCKS,
        "paragraph_open": PreparedParagraph,
        "h1": PreparedH1, "h2": PreparedH2, "h3": PreparedH3,
        "h4": PreparedH4, "h5": PreparedH5, "h6": PreparedH6,
    }

    def native_body_ready(self) -> bool:
        return super().native_body_ready() and not self.loading

    def _measured_virtual_size_requires_layout(self) -> bool:
        # Markdown extent comes from its arranged blocks, not a separately
        # authored virtual document. Committing that result must not feed it
        # back into the same ancestor measurements. Actual scrollbar changes
        # and content/stylesheet updates retain their ordinary invalidation.
        return False

    def __init__(
        self, markdown: str | None = None, *, name: str | None = None,
        id: str | None = None, classes: str | None = None,
        parser_factory: Callable[[], MarkdownIt] | None = None, open_links: bool = False,
        markdown_part: PreparedMarkdownPart | None = None,
    ) -> None:
        self._prepared_markdown: PreparedMarkdown | None = None
        self._markdown_part = markdown_part
        factory = self._make_parser if parser_factory is None else parser_factory
        super().__init__(markdown, name=name, id=id, classes=classes,
                         parser_factory=factory, open_links=open_links)

    @property
    def partitionable_syntax(self) -> bool:
        """Only the original conversation factory declares this grammar.

        An overridden factory or arbitrary custom parser has no declaration
        permitting conversation-syntax partitioning, even if today's output
        happens to look the same.
        """
        return getattr(self._parser_factory, "__func__", None) is ConversationMarkdown._make_parser

    def acquired_source(self, markdown: str) -> str | PreparedMarkdownPart:
        part = self._markdown_part
        return part if part is not None and part.text == markdown else markdown

    def update_part(self, part: PreparedMarkdownPart) -> AwaitComplete:
        self._markdown_part = part
        return self.update(part.text)

    def reconstructible_children(self) -> tuple[Widget, ...]:
        """Native resources rebuilt from this document's original source."""
        return tuple(child for child in self.children if isinstance(child, MarkdownBlock))

    def _initialize_document(self, markdown: str | None) -> AwaitComplete:
        # Mount admits the body; its materialization worker owns prepared
        # content. Observe that original receipt after completion; waiting on
        # this pump would hold wheel delivery behind background preparation.
        # Native source consumption and TOC completion remain unchanged.
        super()._initialize_document(markdown).call_when_ready(self)
        return AwaitComplete.nothing()

    def retire_body_resources(self) -> None:
        """Release reconstructible preparation with the native retirement."""
        self._prepared_markdown = None

    async def materialize_native_body(self) -> None:
        await self._update_body_source(self.source)

    def update(self, markdown: str) -> AwaitComplete:
        return self.publish_body(partial(self._update_body_source, markdown))

    def append(self, markdown: str) -> AwaitComplete:
        return self.publish_body(partial(self._append_body_source, markdown))

    def _update_body_source(self, markdown: str) -> AwaitComplete:
        if self._markdown_part is not None and self._markdown_part.text != markdown:
            self._markdown_part = None
        return super().update(markdown)

    def _append_body_source(self, markdown: str) -> AwaitComplete:
        if self._markdown_part is not None and self._markdown_part.text != self.source + markdown:
            self._markdown_part = None
        return super().append(markdown)

    def on_unmount(self) -> None:
        self._prepared_markdown = None

    async def _parse_tokens(
        self, parser: MarkdownIt | _ThreadLocalPathParser, markdown: str, *, use_thread: bool,
    ) -> list[Token] | None:
        # Custom parser factories retain their native semantics. This process
        # function implements the declaration-owned conversation/path parser.
        parent = self.parent
        if type(parser) is not _ThreadLocalPathParser:
            tokens = await super()._parse_tokens(parser, markdown, use_thread=use_thread)
            if tokens is not None:
                prepared = await asyncio.to_thread(
                    PreparedMarkdown(tokens, {}).acquire_inline_content, tokens,
                )
                if self._closing or self._pruning or self.parent is not parent:
                    return None
                self._prepared_markdown = prepared
            return tokens
        if not isinstance(self.app, ToadApp):
            source = self.acquired_source(markdown)
            def acquire_local():
                tokens = (parser.resolve_tokens(source.acquire_tokens())
                          if isinstance(source, PreparedMarkdownPart) else parser.parse(source))
                return PreparedMarkdown(tokens, {}).acquire_inline_content(tokens)

            prepared = await asyncio.to_thread(acquire_local)
            if self._closing or self._pruning or self.parent is not parent:
                return None
            self._prepared_markdown = prepared
            return prepared.tokens

        # Runway and delivery use the same pure preparation key. Filesystem
        # links are resolved only in each independent delivered token resource,
        # after highlighting; they never become reusable renderer inputs.
        while not self._closing and self.is_attached and not self._pruning:
            theme = (self.app.native_ansi_color, self.app.current_theme.dark)
            request = self.app.render_processes.submit(MarkdownRenderTask(self.acquired_source(markdown), *theme))
            worker = self.run_worker(request, group="markdown-preparation", exit_on_error=False)
            try:
                prepared = await worker.wait()
            except WorkerCancelled:
                if self._closing or self._pruning or not self.is_attached:
                    return None
                raise asyncio.CancelledError
            if (self._closing or not self.is_attached or self._pruning
                    or self.parent is not parent):
                return None
            def acquire():
                tokens = parser.resolve_tokens(prepared.tokens)
                return prepared.acquire_inline_content(tokens)

            prepared = await asyncio.to_thread(acquire)
            tokens = prepared.tokens
            if (self._closing or not self.is_attached or self._pruning
                    or self.parent is not parent):
                return None
            if theme != (self.app.native_ansi_color, self.app.current_theme.dark):
                continue
            self._prepared_markdown = prepared
            return tokens
        return None

    def _get_prepared_fence(self, code: str, language: str, ansi: bool, dark: bool) -> Content | None:
        resource = self._prepared_markdown
        prepared = None if resource is None else resource.fences.get((code, language, ansi, dark))
        return None if prepared is None else prepared.content

    def _get_token_content(self, token: Token, *, block: MarkdownBlock) -> Content:
        # The native document owns this token cohort. Content was acquired
        # with resolved links off-loop; no widget recomputes its source spans.
        if type(block)._token_to_content is not MarkdownBlock._token_to_content:
            # A custom block owns its converter, including any widget context.
            # Its declared answer cannot be replaced by the native pure result.
            return super()._get_token_content(token, block=block)
        assert self._prepared_markdown is not None
        return self._prepared_markdown.inline_content(token)

    def get_block_class(self, block_name: str) -> type[MarkdownBlock]:
        if block_name in {"fence", "code_block"}:
            return PreparedCodeFence
        return super().get_block_class(block_name)


class PreparedCodeLabel(Label, PreparedMarkdownContent):
    """Code uses the same native Content worker and publication lifetime."""


class PreparedCodeFence(ConversationCodeFence):
    def set_content(self, content: Content) -> None:
        self._content = content
        label = self.query_one_optional("#code-content", PreparedCodeLabel)
        if label is not None:
            label.update(content)

    def compose(self) -> ComposeResult:
        yield PreparedCodeLabel(self._highlighted_code, id="code-content", expand=True)
