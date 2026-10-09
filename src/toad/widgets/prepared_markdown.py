"""Use the app-owned CPU pool for heavy conversation Markdown preparation."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import Callable
from functools import cached_property, partial
from typing import cast

from markdown_it import MarkdownIt
from markdown_it.token import Token


from textual.content import Content
from textual import constants, log
from textual.app import ComposeResult
from textual.worker import WorkerCancelled, get_current_worker
from textual.await_complete import AwaitComplete
from textual.widget import Widget
from textual.visual import Visual
from textual.widgets import Label
from textual.widgets._markdown import Markdown, MarkdownBlock

from toad.app import ToadApp
from toad.conversation_markdown import ConversationCodeFence, ConversationMarkdown, _ThreadLocalPathParser
from toad.markdown_preparation import PreparedContentRange, PreparedMarkdown, PreparedMarkdownPart
from toad.block_content import MarkdownBlockContent
from toad.block_navigation import ChildBlockCursor, DocumentBlockCursor
from toad.layout import trim_trailing_margin
from toad.render_tasks import MarkdownRenderTask, MarkdownDocumentRenderTask
from toad.work_preparation import retained_bytes
from toad.widgets.viewport_body import MeasuredViewportBody, PreparedDocumentBody
from toad.widgets.worker_static import WorkerStatic


class PreparedMarkdownContent:
    """Native blocks keep token/link custody; WorkerStatic owns their wrapping."""

    @classmethod
    def document_node(cls, block):
        # WorkerStatic changes scene execution, not the native content/layout
        # declaration. Custom scene behavior still needs its explicit supplier.
        cls._require_native_document(
            width=WorkerStatic.get_content_width, height=WorkerStatic.get_content_height,
            selection=WorkerStatic.get_selection,
        )
        cls._require_document_methods({"render_line": WorkerStatic.render_line})
        return cls.native_document_node(block)

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


class PreparedParagraph(PreparedMarkdownContent, ConversationMarkdown.BLOCKS["paragraph_open"], WorkerStatic):
    pass


class PreparedH1(PreparedMarkdownContent, ConversationMarkdown.BLOCKS["h1"], WorkerStatic):
    pass


class PreparedH2(PreparedMarkdownContent, ConversationMarkdown.BLOCKS["h2"], WorkerStatic):
    pass


class PreparedH3(PreparedMarkdownContent, ConversationMarkdown.BLOCKS["h3"], WorkerStatic):
    pass


class PreparedH4(PreparedMarkdownContent, ConversationMarkdown.BLOCKS["h4"], WorkerStatic):
    pass


class PreparedH5(PreparedMarkdownContent, ConversationMarkdown.BLOCKS["h5"], WorkerStatic):
    pass


class PreparedH6(PreparedMarkdownContent, ConversationMarkdown.BLOCKS["h6"], WorkerStatic):
    pass


class PreparedCodeLabel(PreparedMarkdownContent, Label, WorkerStatic):
    """Code uses the same native Content worker and publication lifetime."""


class PreparedCodeFence(ConversationCodeFence):
    def set_content(self, content: Content) -> None:
        self._content = content
        label = self.query_one_optional("#code-content", PreparedCodeLabel)
        if label is not None:
            label.update(content)

    def compose(self) -> ComposeResult:
        yield PreparedCodeLabel(self._highlighted_code, id="code-content", expand=True)

    @classmethod
    def document_node(cls, block):
        cls._require_native_document(constructor=ConversationCodeFence.__init__,
                                     set_content=PreparedCodeFence.set_content)
        cls._require_document_methods({"compose": PreparedCodeFence.compose})
        return block.fence_node(label_type=PreparedCodeLabel)

    @classmethod
    def document_declarations(cls):
        return cls, PreparedCodeLabel


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
        "fence": PreparedCodeFence, "code_block": PreparedCodeFence,
    }

    @cached_property
    def _document_block_cursor(self):
        return DocumentBlockCursor(self)

    @cached_property
    def _native_block_cursor(self):
        return ChildBlockCursor(self)

    @property
    def block_cursor(self):
        # Renderer retirement/acquisition does not change source selection.
        # Only a custom grammar retains its original scene cursor contract.
        if self.partitionable_syntax:
            return self._document_block_cursor
        return self._native_block_cursor

    @property
    def block_document_paint(self):
        """Borrow the body's original resource without extending paint custody.

        Source-copy admission is distinct from selected-row/style readiness.
        A preceding publication can still supply this source while its new
        presentation prepares, but never a replacement source or detached view.
        """
        paint = self._body_measurement.document_paint
        document = self.get_current_document()
        if (not self.is_attached or self._closing or paint is None or document is None
                or document.source != self.source
                or not paint.document.same_source(document)):
            return None
        return paint

    def native_body_ready(self) -> bool:
        return super().native_body_ready() and not self.loading

    @property
    def document(self):
        source = self._prepared_markdown
        return None if source is None else source.document

    @document.setter
    def document(self, document):
        if document is None:
            self._prepared_markdown = None
        else:
            assert self._prepared_markdown is not None
            self._prepared_markdown.admit_document(document)

    @property
    def prepared_source(self):
        """Actual acquired source, independent of its current paint receipt."""
        source = self._prepared_markdown
        return (source if self.owns_requested_source() and source is not None and source.document is not None
                and source.document.source == self._pending_source else None)

    def owns_requested_source(self):
        owner = self._content_owner
        return owner is None or getattr(self.parent, "prepared_content", None) is owner

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
        prepared_source: PreparedMarkdown | None = None,
        content_owner: PreparedContentRange | None = None,
    ) -> None:
        self._prepared_markdown = prepared_source
        self._content_owner = content_owner
        self._markdown_part = markdown_part
        # Requested text survives pending publication, cancellation and scene
        # retirement. Native .source describes the text its scene consumed.
        self._pending_source = markdown or ""
        if prepared_source is not None:
            document = prepared_source.document
            if (document is None or document.declaration is not type(self)
                    or document.source != self._pending_source):
                raise RuntimeError("Retained Markdown source does not supply this declaration and request")
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

    def acquired_source(self, markdown: str | PreparedMarkdownPart) -> str | PreparedMarkdownPart:
        if isinstance(markdown, PreparedMarkdownPart):
            return markdown
        part = self._markdown_part
        return part if part is not None and part.text == markdown else markdown

    def update_part(self, part: PreparedMarkdownPart, *, content_owner: PreparedContentRange | None = None) -> AwaitComplete:
        self._content_owner = content_owner
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
        if self._prepared_markdown is not None:
            if self.prepared_source is None:
                raise RuntimeError("Retained Markdown source lost its current native admission")
            self.publish_body(self.materialize_native_body).call_when_ready(self)
        else:
            initial = None if markdown is None and not self._pending_source else self._pending_source
            super()._initialize_document(initial).call_when_ready(self)
        return AwaitComplete.nothing()

    def retire_body_resources(self) -> None:
        """Native controls retire; acquired source belongs to this document.

        Selection, navigation and reflow still need the original resolved
        tokens and document identity. Their lifetime ends at source replacement
        or disposal, not when reconstructible controls leave the scene.
        """

    async def materialize_native_body(self):
        if not self.owns_requested_source():
            return False
        source = self._pending_source
        self._markdown = source
        document = self.get_current_document()
        if document is not None:
            # Width/style demand changes presentation, not parser or resolved
            # link acquisition. Borrow this original delivered source resource.
            return await self._prepare_document(document.with_presentation(self))
        return await self._update_body_source(self.acquired_source(source))

    async def materialize_interactive_body(self):
        # The original pointer owner acquires actual controls before choosing
        # a receiver. It never dispatches a synthetic click against paint.
        if not self.partitionable_syntax:
            # A custom grammar still owns its original scene acquisition.
            await self.publish_body(partial(ConversationMarkdown.update, self, self._pending_source))
            return

        async def acquire_controls():
            # The preceding writer may have delivered a newer source while
            # this publication joined it. Borrow that actual resource here,
            # rather than capturing its predecessor before the join.
            paint = self._body_measurement.document_paint
            current = self.get_current_document()
            if current is None:
                raise RuntimeError("Prepared Markdown interaction has no acquired source document")
            if paint is None:
                raise RuntimeError("Prepared Markdown interaction has no completed document paint")
            if not current.same_source(paint.document):
                raise RuntimeError("Prepared Markdown interaction paint belongs to a different source")
            await self.materialize_document(paint)
            # The native producer checks source custody across its awaits.
            # A revoked acquisition must not be reported as live controls.
            return None if self.is_current_document(paint.document) else False

        if (not self.is_attached or self._closing or not self.body_dormant
                or not self.owns_requested_source()):
            return
        await self.restore_body()
        if (not self.is_attached or self._closing or not self.body_dormant
                or not self.owns_requested_source()):
            return
        await self.publish_body(acquire_controls)

    def get_current_document(self):
        source = self.prepared_source
        return None if source is None else source.document

    @classmethod
    def document_root(cls, document, children):
        cls._require_document_methods({
            "render": Widget.render,
            "get_content_width": MeasuredViewportBody.get_content_width,
            "get_content_height": MeasuredViewportBody.get_content_height,
            "process_layout": ConversationMarkdown.process_layout,
        })
        return cls.native_document_root(document, children)

    def update(self, markdown: str) -> AwaitComplete:
        source = self._request_source(markdown, append=False)
        return self.publish_body(partial(self._update_body_source, self.acquired_source(source)))

    def append(self, markdown: str) -> AwaitComplete:
        source = self._request_source(markdown, append=True)
        return self.publish_body(partial(self._update_body_source, self.acquired_source(source)))

    def _request_source(self, markdown: str, *, append: bool) -> str:
        """Accept a source request once, before its publication can await.

        A worker's cancellation or older snapshot cannot revoke this request
        or discard syntax acquired for a newer one. The existing body writer
        orders publication; reconstruction borrows the current requested text.
        """
        if not self._closing:
            if not append:
                self.block_cursor.clear()
            self._pending_source = self._pending_source + markdown if append else markdown
            # Even an equal-text replacement is a new independent acquisition.
            # Retained rows do not grant the preceding suppliers source custody.
            self._prepared_markdown = None
            if self._markdown_part is not None and self._markdown_part.text != self._pending_source:
                self._markdown_part = None
        return self._pending_source

    async def _update_body_source(self, source: str | PreparedMarkdownPart):
        markdown = source.text if isinstance(source, PreparedMarkdownPart) else source
        if not self.partitionable_syntax:
            # An arbitrary parser/factory hasn't declared the conversation
            # source contract. Its original scene producer still owns blocks,
            # callbacks and any additional token behavior.
            return await ConversationMarkdown.update(self, markdown)
        self._markdown = markdown
        parser = self._parser_factory()
        async with self.lock:
            tokens = await self._parse_tokens(parser, source, use_thread=True)
            if tokens is None:
                return False
            document = self.acquire_document(markdown, tokens)
            return await self._prepare_document(document)

    async def _prepare_document(self, document):
        self.document = document
        source = self._prepared_markdown
        assert source is not None
        writer = get_current_worker()
        parent = self.parent
        screen = self.screen

        def current():
            if (not self.is_attached or self._closing or self._pruning
                    or self.parent is not parent or self.screen is not screen
                    or self.prepared_source is not source):
                return False
            if not self._body_measurement.publishes_from(writer):
                raise RuntimeError("Accepted Markdown source lost its publication worker")
            return True

        app = self.app
        previous_task = None
        while current():
            # Padding is not source allocation. Keep the preceding resource
            # unpublished until native measurement supplies usable columns.
            if self._body_measurement.width <= 0:
                return False
            width = self._body_measurement.width + self.styles.gutter.width
            selection = self.text_selection
            task = MarkdownDocumentRenderTask(
                document, width, root_selection=selection,
                selection_style=Visual.selection_style(self) if selection is not None else None,
                selecting=screen._selecting,
            )
            if (previous_task is not None
                    and task.preparation_inputs == previous_task.preparation_inputs
                    and document.presentation.admission == previous_task.document.presentation.admission):
                raise RuntimeError("Markdown paint refused without changed native inputs")
            paint = (await app.render_processes.submit(task) if isinstance(app, ToadApp)
                     else await asyncio.to_thread(task.execute))
            if not current():
                return False
            paint = paint.with_presentation(
                document, root_selection=task.root_selection,
                selection_style=task.selection_style, selecting=task.selecting,
            )

            def resource_costs():
                seen = set()
                source_cost = retained_bytes(source, seen=seen)
                return retained_bytes(paint, seen=seen), source_cost

            cost, source_cost = (await app.preparation.run_thread(resource_costs)
                                 if isinstance(app, ToadApp) else await asyncio.to_thread(resource_costs))
            if not current():
                return False
            source.retained_bytes = source_cost
            if (paint.is_current(self, width)
                    and self._body_measurement.width + self.styles.gutter.width == width):
                self.document = document
                self.loading = False
                self._table_of_contents = paint.table_of_contents
                self.post_message(Markdown.TableOfContentsUpdated(self, self.table_of_contents).set_sender(self))
                return PreparedDocumentBody(paint, cost, source)
            if constants.LOG_FILE:
                current_document = self.document
                presentation = paint.document.presentation
                admissions = type(presentation).acquire_admissions((self,))
                log("document-paint-refused", body=id(self), declaration=type(self).__name__,
                    width=width, measurement=type(self._body_measurement).__name__,
                    measurement_width=self._body_measurement.width, rows=self.measured_rows,
                    gutter=self.styles.gutter, paint_width=paint.width, content_size=paint.content_size,
                    attached=self.is_attached, closing=self._closing, pruning=self._pruning,
                    document=id(document), source_identity=document.heading_namespace,
                    current_document=None if current_document is None else id(current_document),
                    same_source=(current_document is not None and document.same_source(current_document)),
                    source_current=self.prepared_source is source, owns_source=self.owns_requested_source(),
                    host_empty=self.is_empty, paint_root_empty=paint.root_empty,
                    host_pseudo=frozenset(self.get_pseudo_classes()),
                    source_root_pseudo=presentation.root.pseudo_classes,
                    presentation_current=presentation.current_for(self, admissions=admissions),
                    paint_current=paint.is_current(self, width, admissions=admissions),
                    participant_admission=presentation.admission, current_admission=admissions[self])
            # Sibling mounting, width and selection can change during worker
            # delivery. The same accepted producer reacquires presentation;
            # its original resolved tokens and source suppliers stay intact.
            previous_task = task
            document = document.with_presentation(self)
            self.document = document
        return False

    def goto_anchor(self, anchor: str) -> bool:
        measurement = self._body_measurement
        if isinstance(measurement, PreparedDocumentBody) and measurement.ready(self):
            region = measurement.paint.anchor_region(anchor)
            if region is None:
                return False
            self.scroll_to_region(region, top=True)
            return True
        return super().goto_anchor(anchor)

    def on_unmount(self) -> None:
        self._prepared_markdown = None
        self.document = None

    async def _parse_tokens(
        self, parser: MarkdownIt | _ThreadLocalPathParser, markdown: str | PreparedMarkdownPart, *, use_thread: bool,
    ) -> list[Token] | None:
        # Custom parser factories retain their native semantics. This process
        # function implements the declaration-owned conversation/path parser.
        parent = self.parent
        writer = get_current_worker()

        def current():
            # A preceding writer can remain in the publication chain while a
            # later request joins it. Only the current writer may install source.
            return (not self._closing and not self._pruning
                    and self.parent is parent
                    and self.owns_requested_source()
                    and getattr(self._body_measurement, "worker", None) is writer)

        if type(parser) is not _ThreadLocalPathParser:
            markdown = markdown.text if isinstance(markdown, PreparedMarkdownPart) else markdown
            tokens = await super()._parse_tokens(parser, markdown, use_thread=use_thread)
            if tokens is not None:
                prepared = await asyncio.to_thread(
                    PreparedMarkdown(tokens, {}).acquire_inline_content, tokens,
                )
                if not current():
                    return None
                self._prepared_markdown = prepared
            return tokens
        if not isinstance(self.app, ToadApp):
            source = markdown
            def acquire_local():
                tokens = (parser.resolve_tokens(source.acquire_tokens())
                          if isinstance(source, PreparedMarkdownPart) else parser.parse(source))
                return PreparedMarkdown(tokens, {}).acquire_inline_content(
                    tokens, syntax=source if isinstance(source, PreparedMarkdownPart) else None)

            prepared = await asyncio.to_thread(acquire_local)
            if not current():
                return None
            self._prepared_markdown = prepared
            return prepared.tokens

        # Runway and delivery use the same pure preparation key. Filesystem
        # links are resolved only in each independent delivered token resource,
        # after highlighting; they never become reusable renderer inputs.
        while not self._closing and self.is_attached and not self._pruning:
            theme = (self.app.native_ansi_color, self.app.current_theme.dark)
            request = self.app.render_processes.submit(MarkdownRenderTask(markdown, *theme))
            worker = self.run_worker(request, group="markdown-preparation", exit_on_error=False)
            try:
                prepared = await worker.wait()
            except WorkerCancelled:
                if self._closing or self._pruning or not self.is_attached:
                    return None
                raise asyncio.CancelledError
            if not self.is_attached or not current():
                return None
            def acquire():
                tokens = parser.resolve_tokens(prepared.tokens)
                return prepared.acquire_inline_content(
                    tokens, syntax=markdown if isinstance(markdown, PreparedMarkdownPart) else None)

            prepared = await asyncio.to_thread(acquire)
            tokens = prepared.tokens
            if not self.is_attached or not current():
                return None
            if theme != (self.app.native_ansi_color, self.app.current_theme.dark):
                continue
            self._prepared_markdown = prepared
            return tokens
        return None

    def _get_prepared_fence(self, code: str, language: str, ansi: bool, dark: bool) -> Content | None:
        resource = self._prepared_markdown
        return None if resource is None else resource.fence_content(code, language, ansi, dark)

    def acquire_document_content(self):
        """Lend original resolved tokens/content, never a bound widget hook."""
        assert self._prepared_markdown is not None
        return self._prepared_markdown.inline_content

    def acquire_document_fences(self):
        assert self._prepared_markdown is not None
        return self._prepared_markdown.fence_content

    def get_document_process_layout(self):
        return trim_trailing_margin

    def _get_token_content(self, token: Token, *, block: MarkdownBlock) -> Content:
        # The native document owns this token cohort. Content was acquired
        # with resolved links off-loop; no widget recomputes its source spans.
        if type(block)._token_to_content is not MarkdownBlock._token_to_content:
            # A custom block owns its converter, including any widget context.
            # Its declared answer cannot be replaced by the native pure result.
            return super()._get_token_content(token, block=block)
        assert self._prepared_markdown is not None
        return self._prepared_markdown.inline_content(token)
