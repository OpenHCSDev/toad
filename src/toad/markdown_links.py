"""One syntax and link resolver for line, inline and Textual Markdown views."""

from __future__ import annotations

import re
from abc import abstractmethod
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from threading import local
from typing import TYPE_CHECKING

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.display_references import ReferenceContext
from agent_comms.nominal.field_codec import FieldCodec
from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token

from toad.file_position import FilePosition
from toad.line_blocks import LineLink, LinkHref, OpenReference
from toad.project_link import ProjectLink
from toad.prompt.extract import extract_paths_from_prompt

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
        candidates = []
        # The composer and ACP builder own the @file grammar. Preserve the
        # complete quoted spelling, including spaces, when linking it here.
        for path, start, end in extract_paths_from_prompt(text):
            link = ProjectLink.file_spelling(self.root, path, search=False)
            if link is not None:
                content = Token("text", "", 0, content=text[start:end])
                candidates.append((start, end, link.inline_tokens(content)))
        for match in _PATH_PATTERN.finditer(text):
            link = ProjectLink.from_path(self.root, match.group())
            tokens = link.inline_tokens(Token("text", "", 0, content=match.group()))
            candidates.append((match.start(), match.end(), tokens))
        for match in self.references.find(text):
            content = Token("text", "", 0, content=text[match.start : match.end])
            candidates.append((match.start, match.end, OpenReference(match.reference).inline_tokens(content)))
        found = []
        for start, end, tokens in candidates:
            if tokens and not any(left < end and start < right for left, right, _ in found):
                found.append((start, end, tokens))
        return sorted(found)


class JoinedLines:
    """Paragraph source lines join with a space, as Markdown draws them."""

    @staticmethod
    def softbreak(token: Token) -> Token:
        return token


class QuotedLines(JoinedLines):
    """Every quoted source line stays its own line, as greentext."""

    @staticmethod
    def softbreak(token: Token) -> Token:
        return Token("hardbreak", "br", 0)


@dataclass(slots=True)
class _ProjectTokens:
    links: LinkContext
    linked: int = 0
    # The innermost open block decides how a source newline inside it is drawn.
    lines: list[type[JoinedLines]] = field(default_factory=lambda: [JoinedLines])


class ProjectTokenRule(DeclaredFamily, affix="TokenRule"):
    @classmethod
    @abstractmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens): ...


class InlineTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        if token.children:
            token.children = renderer.resolve(token.children, _ProjectTokens(context.links, lines=context.lines))
        return [token]


class BlockquoteOpenTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        context.lines.append(QuotedLines)
        return [token]


class BlockquoteCloseTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        context.lines.pop()
        return [token]


class SoftbreakTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer: ProjectTokenRenderer, token: Token, context: _ProjectTokens):
        return [context.lines[-1].softbreak(token)]


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


class _MarkdownParserState(local):
    def __init__(self):
        self.parser = MarkdownIt("gfm-like")
        self.parser.validateLink = ProjectLink.opens
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
