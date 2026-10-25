"""One syntax and link resolver for line, inline and Textual Markdown views."""

from __future__ import annotations

import re
from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from threading import local
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from agent_comms.display_references import ReferenceContext
from agent_comms.field_codec import FieldCodec
from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token

from toad.file_position import FilePosition
from toad.line_blocks import LineLink, LinkHref, OpenReference
from toad.project_link import ProjectLink

if TYPE_CHECKING:
    from textual.widget import Widget


_PATH_PATTERN = re.compile(
    r"(?<![\w:/@#])"
    r"(?P<path>(?:(?:~|\.{1,2})?/)?(?:[\w.@+-]+/)+[\w.@+-]+|[\w.@+-]+\.[A-Za-z0-9][\w+-]*)"
    rf"(?:{FilePosition.pattern})?"
    r"(?![\w/])"
)


@dataclass(frozen=True)
class LinkContext:
    """Original filesystem and Core observation, captured once per render job."""

    root: Path
    references: ReferenceContext

    @classmethod
    async def acquire(cls, widget):
        context = cls.containing(widget)
        access = widget.app.coordination_access
        references = await context.references.acquire_from(partial(access.observation.current_references, access))
        return cls(context.root, references)

    @classmethod
    def containing(cls, widget: Widget):
        from toad.project_path_owner import ProjectPathOwner

        owner = ProjectPathOwner.containing(widget)
        return cls(owner.project_root.resolve(), owner.reference_context)

    def current_for(self, widget: Widget):
        if widget.is_attached:
            return self == self.containing(widget)
        return False

    def for_source(self, source):
        return LinkContext(self.root, self.references.for_source(source))

    def matches(self, text: str):
        found = []
        for match in _PATH_PATTERN.finditer(text):
            link = ProjectLink.from_path(self.root, match.group())
            tokens = link.inline_tokens(Token("text", "", 0, content=match.group()))
            if tokens:
                found.append((match.start(), match.end(), tokens))
        for match in self.references.find(text):
            if any(start < match.end and match.start < end for start, end, _ in found):
                continue
            content = Token("text", "", 0, content=text[match.start : match.end])
            found.append((match.start, match.end, OpenReference(match.reference).inline_tokens(content)))
        return sorted(found)


@dataclass(slots=True)
class _ProjectTokens:
    links: LinkContext
    linked: int = 0


class ProjectTokenRule(DeclaredFamily, affix="TokenRule"):
    @classmethod
    @abstractmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens): ...


class InlineTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        if token.children:
            token.children = renderer.resolve(token.children, _ProjectTokens(context.links))
        return [token]


class LinkOpenTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        href = str(token.attrGet("href") or "")
        target = ProjectLink.from_href(lambda: context.links.root, href)
        token.attrSet("href", LinkHref.capture(target))
        context.linked += 1
        return [token]


class LinkCloseTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        context.linked -= 1
        return [token]


class ImageTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        # Images are links to a local preview or an external address, never network fetches.
        href = str(token.attrGet("src") or "")
        content = Token("text", "", 0, content=token.content or Path(href).name or "Image")
        if context.linked:
            return [content]
        return LineLink.inline_tokens(ProjectLink.from_href(lambda: context.links.root, href), content)


class TextTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        if context.linked:
            return [token]
        result, position = [], 0
        for start, end, tokens in context.links.matches(token.content):
            if start > position:
                result.append(Token(token.type, token.tag, 0, content=token.content[position:start]))
            # Retain inline-code formatting on both linked and unlinked pieces.
            tokens[1].type, tokens[1].tag = token.type, token.tag
            result.extend(tokens)
            position = end
        if not position:
            return [token]
        if position < len(token.content):
            result.append(Token(token.type, token.tag, 0, content=token.content[position:]))
        return result


class CodeInlineTokenRule(TextTokenRule):
    pass


class ProjectTokenRenderer:
    def __init__(self):
        self.rules = {FieldCodec.encode(rule): rule for rule in ProjectTokenRule.members_with(ProjectTokenRule)}

    def resolve(self, tokens: list[Token], context: _ProjectTokens):
        result: list[Token] = []
        for token in tokens:
            rule = self.rules.get(token.type)
            result.extend(rule.resolve(self, token, context) if rule else (token,))
        return result


def greentext_lines(state: StateCore) -> None:
    """Each quoted source line stays its own line, as greentext."""
    depth = 0
    for token in state.tokens:
        if token.tag == "blockquote":
            depth += token.nesting
        if depth and token.children:
            for child in token.children:
                if child.type == "softbreak":
                    child.type = "hardbreak"


class _MarkdownParserState(local):
    def __init__(self):
        self.parser = MarkdownIt("gfm-like")
        self.parser.validateLink = ProjectLink.opens
        self.parser.core.ruler.push("greentext_lines", greentext_lines)
        self.resolver = ProjectTokenRenderer()
        self.syntax_rules = tuple(self.parser.core.ruler.getRules(""))


_parser_state = _MarkdownParserState()


def parse_markdown_syntax(source: str, env=None, *, inline: bool = False):
    state = StateCore(source, _parser_state.parser, {} if env is None else env)
    state.inlineMode = inline
    for rule in _parser_state.syntax_rules:
        rule(state)
    return state.tokens


class MessageMarkdownParser:
    def __init__(self, context: LinkContext):
        self.context = context

    def parse(self, source: str, env=None):
        return self.resolve_tokens(parse_markdown_syntax(source, env))

    def parse_inline(self, source: str):
        return self.resolve_tokens(parse_markdown_syntax(source, inline=True))

    def resolve_tokens(self, tokens: list[Token]):
        # Linkify is syntax: resolve its URLs too, before any frontend sees them.
        return _parser_state.resolver.resolve(tokens, _ProjectTokens(self.context))
