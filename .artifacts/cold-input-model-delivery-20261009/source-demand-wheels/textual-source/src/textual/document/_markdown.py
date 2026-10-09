"""Acquired Markdown source using the native block, CSS and paint owners."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Sequence
from dataclasses import dataclass, replace
from inspect import getattr_static
from uuid import UUID, uuid4

from markdown_it.token import Token

from textual.content import Content
from textual.containers import Horizontal, Vertical
from textual.document._paint import DocumentNode, DocumentPresentation
from textual.widgets._label import Label
from textual.widgets._markdown import (
    Markdown,
    MarkdownBlock,
    MarkdownBullet,
    MarkdownFence,
    MarkdownList,
    MarkdownTableContent,
    MarkdownTableCellContents,
)


class MarkdownSourceBlock:
    """One parsed source identity, separate from a mounted block's custody.

    The original grammar owns staging children. The declaration owns their
    native composition; preparation consumes the completed source cohort.
    """

    def __init__(self, document, declaration, token, source_index, *args):
        self.document = document
        self.declaration = declaration
        self._token = token
        self._arguments = args
        self._blocks = []
        self._inline_token = None
        self._inline_content = None
        self._converter = None
        self.id = None
        self.source_index = source_index
        self.source_range = tuple(token.map) if token.map is not None else (0, 0)
        self.placement = None
        self.bullet = args[0] if args else ""
        self._producer = document.producers[declaration]
        self.code = (
            token.content.rstrip() if issubclass(declaration, MarkdownFence) else None
        )
        self._highlight = None
        if self.code is not None:
            if document.fence_content is not None:
                self._highlight = document.fence_content(
                    self.code,
                    token.info,
                    document.presentation.native_ansi,
                    document.dark,
                )
            self._highlighter = document.highlighters[declaration]

    def _is_block_type(self, declaration):
        return issubclass(self.declaration, declaration)

    def heading_id(self):
        return self.declaration.make_heading_id(
            self._content, f"{self.document.heading_namespace}-{self.source_index}"
        )

    def table_of_contents_entry(self):
        return self.declaration.make_heading_entry(self._content, self.id)

    def build_from_token(self, token):
        self._inline_token = token
        self._converter = self.document.converters[self.declaration]
        if (
            self.document.inline_content is not None
            and self._converter is self.document.native_converter
        ):
            self._inline_content = self.document.inline_content(token)
        else:
            self._inline_content = self._converter(token)

    @property
    def _content(self):
        if self._inline_content is not None:
            return self._inline_content
        return Content()

    def prepare(self):
        return self._producer(self)

    def source_text(self) -> str:
        """Read this original grammar member's bounded source contribution."""
        return MarkdownBlock.source_text(self.document.source, self.source_range)

    def node(self, *, children=(), **kwargs):
        node = DocumentNode(
            self.declaration,
            self._content,
            children=children,
            name=self._token.type,
            id=self.id,
            classes=f"level-{self._token.level}",
            expand=True,
            pseudo_classes=self.document.child_pseudo_classes,
            source_range=self.source_range,
            source_index=self.source_index,
            **kwargs,
        )
        return node

    def list_node(self, rows):
        pseudo = self.document.child_pseudo_classes
        children = list(
            MarkdownList.compose_rows(
                rows,
                lambda symbol: DocumentNode(
                    MarkdownBullet,
                    Content(symbol),
                    pseudo_classes=pseudo,
                    selection=MarkdownBullet.selection_text,
                ),
                lambda blocks: DocumentNode(
                    Vertical,
                    children=[block.prepare() for block in blocks],
                    pseudo_classes=pseudo,
                ),
                lambda *children: DocumentNode(
                    Horizontal, children=children, pseudo_classes=pseudo
                ),
            )
        )
        return self.node(children=children)

    def table_node(self, headers, rows):
        cells = [
            DocumentNode(
                MarkdownTableCellContents,
                content,
                classes=classes,
                name=name,
                pseudo_classes=self.document.child_pseudo_classes,
            )
            for content, classes, name, _, _ in MarkdownTableContent.cells(
                headers, rows
            )
        ]

        def prepare_grid(node, layout):
            MarkdownTableContent.prepare_grid(layout, node.parent.styles.is_auto_width)

        table = DocumentNode(
            MarkdownTableContent,
            children=cells,
            shrink=True,
            pseudo_classes=self.document.child_pseudo_classes,
            inline_rules={"grid_size_columns": len(headers)},
            pre_layout=prepare_grid,
        )
        return self.node(children=(table,))

    def fence_node(self, *, label_type: type[Label] = Label):
        """Compose the declared label using the original fence content owner.

        A prepared scene may declare a different label capability. Its CSS
        identity belongs to that declaration; the fence still owns highlighting
        and code-label attributes.
        """
        content = self.highlight(
            self.document.presentation.native_ansi, self.document.dark
        )
        label = MarkdownFence.code_label(
            content,
            lambda content, **attributes: DocumentNode(
                label_type,
                content,
                pseudo_classes=self.document.child_pseudo_classes,
                **attributes,
            ),
        )
        return self.node(children=(label,), auto_links=False)

    def highlight(self, ansi: bool, dark: bool) -> Content:
        """Use this acquired fence supplier for detached and scene lifetimes."""
        if (
            ansi == self.document.presentation.native_ansi
            and dark == self.document.dark
            and self._highlight is not None
        ):
            return self._highlight
        content = (
            None if self.document.fence_content is None else
            self.document.fence_content(self.code, self._token.info, ansi, dark)
        )
        return (
            self._highlighter(self.code, self._token.info, ansi=ansi, dark=dark)
            if content is None else content
        )


@dataclass(frozen=True, eq=False)
class MarkdownDocument:
    """Frozen source and presentation, reusable across scene eviction.

    A fresh preparation uses native source nodes and native CSS/layout/paint.
    It retains no widget, App, message task or preceding scene revision.
    """

    source: str
    tokens: Sequence[Token]
    declaration: type[Markdown]
    child_pseudo_classes: frozenset[str]
    dark: bool
    process_layout: object
    block_classes: dict
    producers: dict
    converters: dict
    highlighters: dict
    native_converter: object
    inline_content: object
    fence_content: object
    unhandled: object
    root_producer: object
    bullets: tuple[str, ...]
    presentation: DocumentPresentation
    _source_key: tuple
    _source_identity: UUID

    @property
    def heading_namespace(self):
        return self._source_identity.hex

    @classmethod
    def acquire(cls, owner: Markdown, source: str, tokens: Sequence[Token]):
        if not isinstance(tokens, Sequence):
            raise TypeError(
                "Document preparation requires an acquired materialized token resource"
            )
        # The parser's acquired cohort is owned by the request. Copies and
        # construction belong to prepare(), on the original preparation worker.
        declaration = type(owner)
        root_pseudo_classes = frozenset(owner.get_pseudo_classes())
        child_pseudo_classes = frozenset(
            {
                "blur",
                "disabled" if owner.is_disabled else "enabled",
                *(
                    name
                    for name in ("dark", "light", "inline", "ansi", "nocolor")
                    if name in root_pseudo_classes
                ),
            }
        )
        dark = owner.app.current_theme.dark
        process_layout = owner.get_document_process_layout()
        ancestor_pseudo_classes = owner.get_document_ancestor_pseudo_classes()
        block_classes = owner.acquire_document_blocks()
        producers = {
            block_type: block_type.document_node
            for block_type in block_classes.values()
        }
        converters = {}
        highlighters = {}
        inline_content = owner.acquire_document_content()
        fence_content = owner.acquire_document_fences()
        unhandled = owner.acquire_document_unhandled()
        for block_type in block_classes.values():
            converter = getattr_static(block_type, "_token_to_content")
            if not isinstance(converter, staticmethod):
                raise TypeError(
                    f"{block_type.__name__} needs a detached content producer"
                )
            converters[block_type] = converter.__func__
            if issubclass(block_type, MarkdownFence):
                highlighter = block_type.highlight
                if (
                    fence_content is None
                    and highlighter.__func__ is not MarkdownFence.highlight.__func__
                ):
                    raise TypeError(
                        f"{block_type.__name__} needs acquired document highlighting"
                    )
                highlighters[block_type] = highlighter
        bullets = tuple(owner.BULLETS)
        declarations = {
            declaration,
            *(
                support
                for block_type in block_classes.values()
                for support in block_type.document_declarations()
            ),
        }
        presentation = DocumentPresentation.acquire(
            owner, declarations, ancestor_pseudo_classes=ancestor_pseudo_classes
        )
        root_producer = declaration.document_root
        source_key = (
            source,
            root_producer,
            tuple(
                (
                    name,
                    block_type,
                    producers[block_type],
                    converters[block_type],
                    highlighters.get(block_type),
                )
                for name, block_type in sorted(block_classes.items())
            ),
            bullets,
            process_layout,
            ancestor_pseudo_classes,
            cls._supplier_identity(inline_content),
            cls._supplier_identity(fence_content),
            cls._supplier_identity(unhandled),
        )
        return cls(
            source,
            tokens,
            declaration,
            child_pseudo_classes,
            dark,
            process_layout,
            block_classes,
            producers,
            converters,
            highlighters,
            MarkdownBlock._token_to_content,
            inline_content,
            fence_content,
            unhandled,
            root_producer,
            bullets,
            presentation,
            source_key,
            uuid4(),
        )

    @staticmethod
    def _supplier_identity(supplier):
        if supplier is None:
            return None
        if hasattr(supplier, "__self__"):
            from textual.widget import Widget

            if isinstance(supplier.__self__, Widget):
                raise TypeError("Detached content supplier cannot borrow a live widget")
            return id(supplier.__self__), supplier.__func__
        return id(supplier)

    @property
    def source_key(self):
        """Original acquisition identity and complete grammar/supplier inputs."""
        return self._source_identity, self._source_key

    def same_source(self, other):
        # Acquisition owns this identity; it survives worker serialization.
        # Equal text or a new resolved cohort cannot replace this source.
        return self.source_key == other.source_key

    def with_presentation(self, owner: Markdown) -> MarkdownDocument:
        """Reacquire only current declarations/style, retaining this exact source.

        The owner must retain the delivered tokens/content without mutation.
        New source or newly resolved links require a new acquisition. Neither
        this method nor acquire() copies or traverses the token resource.
        """
        current = type(self).acquire(owner, self.source, self.tokens)
        return replace(current, _source_identity=self._source_identity)

    def root_node(self, children):
        return DocumentNode(
            self.declaration,
            children=children,
            name=self.presentation.root.name,
            id=self.presentation.root.id,
            classes=self.presentation.root.classes,
            pseudo_classes=self.presentation.root.pseudo_classes,
            inline_rules=self.presentation.root.inline_rules,
            process_layout=self.process_layout,
        )

    def prepare(
        self, width: int, *, root_selection=None, selections=None,
        selection_style=None, selecting=False,
    ):
        # Mutable parsing/construction state is local to this preparation, not
        # retained alongside the source and not shared by width workers.
        blocks = []
        tokens = deepcopy(tuple(self.tokens))

        def create(name, token, *args):
            block = MarkdownSourceBlock(
                self, self.block_classes[name], token, len(blocks), *args
            )
            blocks.append(block)
            return block

        roots = tuple(
            block
            for block in Markdown._build_blocks(
                tokens,
                create,
                (
                    (lambda token: None)
                    if self.unhandled is None
                    else lambda token: self.unhandled(token, create)
                ),
                self.bullets,
            )
            if block is not None
        )
        blocks = tuple(blocks)
        for block in blocks:
            block._blocks = tuple(block._blocks)
        root = self.root_producer(self, [block.prepare() for block in roots])
        return self.presentation.prepare(
            root,
            width,
            document=self,
            roots=roots,
            headings=tuple(Markdown.heading_entries(roots)),
            root_selection=root_selection,
            selections=selections,
            selection_style=selection_style,
            selecting=selecting,
        )
