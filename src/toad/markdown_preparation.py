"""Process-safe conversation parsing and code-fence highlighting data."""

from copy import deepcopy
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from markdown_it.token import Token
from rich.console import Console
from rich.markdown import BlockQuote, CodeBlock, Markdown
from rich.padding import Padding
from rich.segment import Segment
from rich.syntax import Syntax
from toad.markdown_links import MessageMarkdownParser, parse_markdown_syntax


class StyledCodeBlock(CodeBlock):
    def on_leave(self, context):
        super().on_leave(context)
        syntax = Syntax(str(self.text).rstrip().expandtabs(4), self.lexer_name, theme=self.theme)
        self.text = syntax.highlight(syntax.code)
        self.text.rstrip()
        self.text.overflow = "fold"

    def __rich_console__(self, console, options):
        yield Padding(self.text, 1, style=self.text.style)


class GreenText(BlockQuote):
    """A quoted line keeps its `>` and reads green."""

    style_name = "green"

    def __rich_console__(self, console, options):
        marker, new_line = Segment("> ", self.style), Segment("\n")
        for line in console.render_lines(self.elements, options.update(width=options.max_width - 2), style=self.style):
            yield marker
            yield from line
            yield new_line


class MarkdownStyleConsole(Console):
    """Rich builds its styled element tree; width-dependent rendering runs later."""

    def render(self, renderable, options=None):
        self.parts.append(renderable)
        return iter(())

    def prepare(self, text, context):
        self.parts = []
        markdown = Markdown("")
        markdown.elements = {**markdown.elements, "fence": StyledCodeBlock, "code_block": StyledCodeBlock,
                             "blockquote_open": GreenText}
        markdown.parsed = MessageMarkdownParser(context).parse(text)
        for segment in markdown.__rich_console__(self, self.options):
            self.parts.append(segment)
        return tuple(self.parts)


@dataclass(frozen=True)
class PreparedMarkdownPart:
    """Source and syntax acquired through the conversation parser declaration.

    Syntax precedes project-link resolution. Every document acquires its own
    mutable tokens; neither partitioning nor presentation mutates this source.
    Custom parser grammars retain their native acquisition instead.
    """

    text: str = field(compare=False)
    tokens: tuple[Token, ...] = field(compare=False, repr=False)
    @classmethod
    def capture(cls, text: str) -> "PreparedMarkdownPart":
        return cls(text, tuple(parse_markdown_syntax(text)))

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



