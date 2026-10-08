"""Process-safe conversation parsing and code-fence highlighting data."""

from dataclasses import dataclass, field
from functools import cached_property

from markdown_it.token import Token
from textual.content import Content
from textual.widgets._markdown import MarkdownBlock, MarkdownFence


FenceKey = tuple[str, str, bool, bool]


@dataclass(frozen=True)
class PreparedMarkdownPart:
    """One bounded native source part, without an invented transcript role."""

    text: str

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
    inlines: dict[int, Content] = field(default_factory=dict)

    def acquire_inline_content(self, tokens: list[Token]) -> "PreparedMarkdown":
        """Bind native content to the actual delivered, link-resolved tokens.

        Token identities belong to this one acquisition, not the reusable
        parser result or another document. Native block construction consumes
        these same token objects and retains the resulting Content itself.
        """
        def descendants(source):
            for token in source:
                yield token
                if token.children is not None:
                    yield from descendants(token.children)

        inlines = {id(token): MarkdownBlock._token_to_content(token)
                   for token in descendants(tokens) if token.type == "inline"}
        return PreparedMarkdown(tokens, self.fences, inlines)


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
