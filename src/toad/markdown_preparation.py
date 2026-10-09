"""Process-safe conversation parsing and code-fence highlighting data."""

from contextlib import ExitStack
from copy import deepcopy
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from hashlib import sha256
import pickle
from typing import TYPE_CHECKING

from markdown_it.token import Token
from textual.content import Content
from textual.widgets._markdown import MarkdownBlock, MarkdownFence

if TYPE_CHECKING:
    from textual.document._markdown import MarkdownDocument


FenceKey = tuple[str, str, bool, bool]


@dataclass(frozen=True)
class PreparedMarkdownPart:
    """Source and syntax acquired through the conversation parser declaration.

    Syntax precedes project-link resolution. Every document acquires its own
    mutable tokens; neither partitioning nor presentation mutates this source.
    Custom parser grammars retain their native acquisition instead.
    """

    text: str = field(compare=False)
    tokens: tuple[Token, ...] = field(compare=False, repr=False)
    revision: bytes = field(init=False)

    def __post_init__(self) -> None:
        # Source acquisition/partitioning runs in preparation. Native refresh
        # compares this revision without walking an arbitrarily nested tree.
        object.__setattr__(self, "revision", sha256(pickle.dumps((self.text, self.tokens), protocol=5)).digest())

    @classmethod
    def capture(cls, text: str) -> "PreparedMarkdownPart":
        from toad.conversation_markdown import parse_markdown_syntax

        return cls(text, tuple(parse_markdown_syntax(text)))

    def acquire_tokens(self) -> list[Token]:
        return deepcopy(list(self.tokens))

    @property
    def syntax(self):
        return self

    def body(self, declaration, **kwargs):
        return declaration(self.text, markdown_part=self, **kwargs)

    async def prepare(self, renderer, ansi, dark):
        from toad.render_tasks import MarkdownRenderTask

        await renderer.prepare(MarkdownRenderTask(self, ansi, dark))

    def resolved_sources(self):
        return ()

    def independent(self):
        return self

    def release_source(self):
        return self

    def select_blocks(self, text: str, first: int, tokens: slice) -> "PreparedMarkdownPart":
        """Select complete top-level blocks, retaining their closing tokens."""
        if text == self.text and first == 0 and tokens.start == 0 and tokens.stop == len(self.tokens):
            return self
        selected = deepcopy(list(self.tokens[tokens]))
        for token in self._descendants(selected):
            if token.map is not None:
                token.map = [line - first for line in token.map]
        return PreparedMarkdownPart(text, tuple(selected))

    def select_table_rows(self, ranges: Iterable[tuple[int, int]]) -> Iterator["PreparedMarkdownPart"]:
        """Repeat the original parsed header, never parse a synthetic table."""
        lines = self.text.splitlines(keepends=True)
        rows = {}
        body_first = body_stop = 0
        for index, token in enumerate(self.tokens):
            if token.type == "tbody_open":
                body_first = index + 1
            elif token.type == "tbody_close":
                body_stop = index
                break
            elif body_first and token.type == "tr_open":
                assert token.map is not None
                rows[token.map[0]] = index
        table = self.tokens[0]
        assert table.type == "table_open" and table.map is not None
        table_stop = table.map[1]
        for first, stop in ranges:
            row_first = rows.get(first, body_stop)
            row_stop = rows.get(stop, body_stop)
            tokens = deepcopy(list((*self.tokens[:body_first],
                                    *self.tokens[row_first:row_stop],
                                    *self.tokens[body_stop:])))
            length = 2 + min(stop, table_stop) - first
            for token in self._descendants(tokens):
                if token.map is None:
                    continue
                if token.type == "table_open":
                    token.map = [0, length]
                elif token.type == "tbody_open":
                    token.map = [2, length]
                elif token.map[0] >= 2:
                    token.map = [line - first + 2 for line in token.map]
            yield PreparedMarkdownPart("".join((*lines[:2], *lines[first:stop])), tuple(tokens))

    @staticmethod
    def _descendants(tokens):
        for token in tokens:
            yield token
            if token.children is not None:
                yield from PreparedMarkdownPart._descendants(token.children)

    @cached_property
    def retained_bytes(self) -> int:
        from toad.work_preparation import retained_bytes

        return retained_bytes(self)


@dataclass(frozen=True)
class PreparedFence:
    content: Content


@dataclass
class PreparedMarkdown:
    tokens: list[Token]
    fences: dict[FenceKey, PreparedFence]
    document: "MarkdownDocument | None" = field(default=None, compare=False, repr=False)
    syntax: PreparedMarkdownPart | None = field(default=None, compare=False, repr=False)
    retained_bytes: int = field(default=0, compare=False, repr=False)

    def admit_document(self, document: "MarkdownDocument") -> None:
        """The independent resolved acquisition owns its native source.

        Pure worker results have no document. acquire_inline_content produces
        a separate resource after project links resolve; only that acquisition
        receives its document. Presentation does not replace its suppliers.
        """
        if self.document is not None and not self.document.same_source(document):
            raise ValueError("A new Markdown source requires its own resolved acquisition")
        self.document = document

    @property
    def text(self):
        if self.document is None:
            raise RuntimeError("Resolved Markdown source has no acquired document")
        return self.document.source

    def body(self, declaration, **kwargs):
        if self.document is None:
            raise RuntimeError("Resolved Markdown source has no acquired document")
        if self.document.declaration is not declaration:
            raise ValueError("Acquired source belongs to a different native declaration")
        return declaration(self.text, markdown_part=self.syntax, prepared_source=self, **kwargs)

    async def prepare(self, renderer, ansi, dark):
        # This independently resolved source has already acquired its content.
        # Width/style paint preparation belongs to the restored body resource.
        return

    def resolved_sources(self):
        return () if self.document is None else (self,)

    def independent(self):
        assert self.syntax is not None
        return self.syntax

    def release_source(self):
        return self.independent()

    def acquire_inline_content(self, tokens: list[Token], *, syntax: PreparedMarkdownPart | None = None) -> "PreparedMarkdown":
        """Bind native content to the actual delivered, link-resolved tokens.

        The parser's token metadata owns its acquired content. Native block
        construction consumes these same tokens, without an identity registry.
        """
        for token in PreparedMarkdownPart._descendants(tokens):
            if token.type == "inline":
                token.meta[PreparedMarkdown] = MarkdownBlock._token_to_content(token)
        return PreparedMarkdown(tokens, self.fences, syntax=self.syntax if syntax is None else syntax)

    def inline_content(self, token: Token) -> Content:
        return token.meta[PreparedMarkdown]

    def fence_content(self, code: str, language: str, ansi: bool, dark: bool) -> Content | None:
        """The acquired theme/source cohort owns highlighted fence content."""
        prepared = self.fences.get((code, language, ansi, dark))
        return None if prepared is None else prepared.content


def prepare_tokens(tokens: list[Token], ansi: bool, dark: bool, *, syntax: PreparedMarkdownPart | None = None) -> PreparedMarkdown:
    fences: dict[FenceKey, PreparedFence] = {}
    for token in tokens:
        if token.type in {"fence", "code_block"}:
            code = token.content.rstrip()
            key = (code, token.info, ansi, dark)
            if key not in fences:
                content = MarkdownFence.highlight(code, token.info, ansi=ansi, dark=dark)
                fences[key] = PreparedFence(content)
    return PreparedMarkdown(tokens, fences, syntax=syntax)


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

    def __init__(self, fragments=(), *, newest: bool = True, batch_size: int = BATCH):
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        self.batch_size = batch_size
        self.admission = None
        self.admitted = ()
        self.fragments = fragments
        selected = self.initial_slice(fragments, batch_size, newest)
        self.start, self.stop = selected.start, selected.stop

    @property
    def start(self):
        return self.admission[0]

    @start.setter
    def start(self, start):
        self.admission = start, self.admission[1] if self.admission is not None else start

    @property
    def stop(self):
        return self.admission[1]

    @stop.setter
    def stop(self, stop):
        self.admission = self.start, stop

    def configure(self, *, batch_size, newest=True):
        self.batch_size = batch_size
        if self.admission is None:
            selected = self.initial_slice(self.fragments, batch_size, newest)
            self.start, self.stop = selected.start, selected.stop

    def resolved_sources(self):
        return tuple(source for resource in self.admitted if resource is not None
                     for source in resource.resolved_sources())

    def acquired(self, index):
        if not self.start <= index < self.stop or not self.admitted:
            return None
        if len(self.admitted) != self.stop - self.start:
            raise RuntimeError("Retained source suppliers do not cover their admission")
        return self.admitted[index - self.start]

    def select_admission(self, selected: slice) -> None:
        """Move demand within this source, retaining its actual common members.

        The supplier tuple belongs to the preceding admitted interval. Rebase
        those original slots before changing its coordinates; an edge or reader
        demand cannot reinterpret them as suppliers for different source parts.
        """
        admitted = tuple(self.acquired(index) for index in range(selected.start, selected.stop)) if self.admitted else ()
        retained = {id(resource) for resource in admitted}
        for resource in self.admitted:
            if resource is not None and id(resource) not in retained:
                resource.release_source()
        self.admission = selected.start, selected.stop
        self.admitted = admitted

    def independent(self):
        source = PreparedContentRange(tuple(fragment.independent() for fragment in self.fragments),
                                      batch_size=self.batch_size)
        source.admission = self.admission
        return source

    def retain_sources(self, view):
        fragments = self.fragments[self.start:self.stop]
        if len(fragments) != len(view.fragment_views):
            raise RuntimeError("Admitted source range lost native members before transfer")
        admitted = tuple(view._retain_fragment_source(fragment, body)
                         for fragment, body in zip(fragments, view.fragment_views))
        retained = {id(resource) for resource in admitted}
        for resource in self.admitted:
            if resource is not None and id(resource) not in retained:
                resource.release_source()
        self.admitted = admitted

    @staticmethod
    def initial_slice(fragments, batch_size: int, newest: bool) -> slice:
        start = max(0, len(fragments) - batch_size) if newest else 0
        return slice(start, min(len(fragments), start + batch_size))

    def compose(self, view):
        view._fragment_views = tuple(view._body(fragment, index)
                                    for index, fragment in enumerate(
                                        self.fragments[self.start:self.stop], self.start))
        yield from view._fragment_views

    def extension_slice(self, older: bool) -> slice:
        return (slice(max(0, self.start - self.batch_size), self.start) if older
                else slice(self.stop, min(len(self.fragments), self.stop + self.batch_size)))

    def update_slice(self, fragments, follow: bool) -> slice:
        if follow:
            return self.initial_slice(fragments, self.batch_size, True)
        stop = min(self.stop, len(fragments))
        return slice(min(self.start, stop), stop)

    async def extend(self, view, older: bool, current: Callable[[], bool], *, prefix=()) -> bool:
        admission = view.capture_admission()
        extension = self.extension_slice(older)
        selected = slice(extension.start if older else self.start,
                         self.stop if older else extension.stop)
        previous = {self.start + index: child for index, child in enumerate(view.fragment_views)}
        return await self.replace_range(
            view, self.fragments, selected, previous,
            lambda: current() and view.capture_admission() == admission,
            prefix=prefix,
        )

    async def replace_range(self, view, fragments, selected, previous, current, *, prefix=()) -> bool:
        """Publish ordered native parts inside their owner's source custody."""
        ordered = []
        added = []
        with ExitStack() as acquisition:
            acquisition.callback(lambda: view.remove_children(added))
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
                        child = view._body(fragments[index], index)
                        added.append(child)
                        batch.append(child)
                    ordered.append(child)
                if batch:
                    await view.mount_all(batch)
                    if not current():
                        return False
            if not current():
                return False
            self.fragments, view._fragment_views = fragments, tuple(ordered)
            self.start, self.stop = selected.start, selected.stop
            self.retain_sources(view)
            desired = (*prefix, *ordered)
            if tuple(view.children) != desired:
                rank = {child: index for index, child in enumerate(desired)}
                view.sort_children(key=lambda child: rank.get(child, len(rank)))
            view.remove_children(tuple(child for child in previous.values() if child not in ordered))
            acquisition.pop_all()
        return True

    def trim(self, view, count: int, *, older: bool) -> None:
        bodies = view.fragment_views
        boundary = count if older else len(bodies) - count
        retired = bodies[:boundary] if older else bodies[boundary:]
        view._fragment_views = bodies[boundary:] if older else bodies[:boundary]
        if older:
            self.start += count
        else:
            self.stop -= count
        self.retain_sources(view)
        view.remove_children(retired)
