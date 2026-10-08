"""Process-safe conversation parsing and code-fence highlighting data."""

from copy import deepcopy
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from hashlib import sha256
import pickle

from markdown_it.token import Token
from textual.content import Content
from textual.widgets._markdown import MarkdownBlock, MarkdownFence


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


@dataclass(frozen=True)
class PreparedMarkdown:
    tokens: list[Token]
    fences: dict[FenceKey, PreparedFence]

    def acquire_inline_content(self, tokens: list[Token]) -> "PreparedMarkdown":
        """Bind native content to the actual delivered, link-resolved tokens.

        The parser's token metadata owns its acquired content. Native block
        construction consumes these same tokens, without an identity registry.
        """
        for token in PreparedMarkdownPart._descendants(tokens):
            if token.type == "inline":
                token.meta[PreparedMarkdown] = MarkdownBlock._token_to_content(token)
        return PreparedMarkdown(tokens, self.fences)

    def inline_content(self, token: Token) -> Content:
        return token.meta[PreparedMarkdown]

    def fence_content(self, code: str, language: str, ansi: bool, dark: bool) -> Content | None:
        """The acquired theme/source cohort owns highlighted fence content."""
        prepared = self.fences.get((code, language, ansi, dark))
        return None if prepared is None else prepared.content


def prepare_tokens(tokens: list[Token], ansi: bool, dark: bool) -> PreparedMarkdown:
    fences: dict[FenceKey, PreparedFence] = {}
    for token in tokens:
        if token.type in {"fence", "code_block"}:
            code = token.content.rstrip()
            key = (code, token.info, ansi, dark)
            if key not in fences:
                content = MarkdownFence.highlight(code, token.info, ansi=ansi, dark=dark)
                fences[key] = PreparedFence(content)
    return PreparedMarkdown(tokens, fences)
