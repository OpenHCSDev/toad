"""Process-safe conversation parsing and code-fence highlighting data."""

from dataclasses import dataclass
from pathlib import Path

from markdown_it.token import Token
from textual.content import Content
from textual.widgets._markdown import MarkdownFence

from toad.conversation_markdown import _ThreadLocalPathParser

FenceKey = tuple[str, str, bool, bool]


@dataclass(frozen=True)
class PreparedFence:
    content: Content
    lines: tuple[Content, ...]


@dataclass(frozen=True)
class PreparedMarkdown:
    tokens: list[Token]
    fences: dict[FenceKey, PreparedFence]


def prepare_tokens(tokens: list[Token], ansi: bool, dark: bool) -> PreparedMarkdown:
    fences = {}
    for token in tokens:
        if token.type in {"fence", "code_block"}:
            code = token.content.rstrip()
            key = (code, token.info, ansi, dark)
            if key not in fences:
                content = MarkdownFence.highlight(code, token.info, ansi=ansi, dark=dark)
                content.get_optimal_width({}, 0)
                fences[key] = PreparedFence(content, tuple(content.split("\n", allow_blank=True)))
    return PreparedMarkdown(tokens, fences)


def prepare_markdown(source: str, project: str, ansi: bool, dark: bool) -> PreparedMarkdown:
    tokens = _ThreadLocalPathParser(Path(project)).parse(source)
    return prepare_tokens(tokens, ansi, dark)
