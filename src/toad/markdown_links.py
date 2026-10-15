"""One syntax and link resolver for line, inline and Textual Markdown views."""
from __future__ import annotations

import re
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import local

from agent_comms.declared_family import DeclaredFamily
from agent_comms.display_references import DisplayReferences
from agent_comms.field_codec import FieldCodec
from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore, inline as inline_rule
from markdown_it.token import Token

from toad.line_blocks import LineLink, OpenReference, OpenUrl
from toad.project_link import ProjectLink
from toad.file_position import FilePosition

_PATH_PATTERN = re.compile(
    r"(?<![\w:/])"
    r"(?P<path>(?:(?:~|\.{1,2})?/)?(?:[\w.@+-]+/)+[\w.@+-]+|[\w.@+-]+\.[A-Za-z0-9][\w+-]*)"
    rf"(?:{FilePosition.pattern})?"
    r"(?![\w/])"
)


@dataclass(frozen=True)
class LinkContext:
    """Original filesystem and Core observation, captured once per render job."""

    root: Path
    references: DisplayReferences

    @classmethod
    async def acquire(cls, widget):
        access = widget.app.coordination_access
        if access.observation is not None:
            await access.current_sidebar()
        return cls.containing(widget)

    @classmethod
    def containing(cls, widget):
        from toad.project_path_owner import ProjectPathOwner
        owner = ProjectPathOwner.containing(widget)
        sidebar = widget.app.coordination_access.sidebar
        references = sidebar.snapshot.references if sidebar is not None and sidebar.snapshot is not None else DisplayReferences()
        if owner.coordination_root is not None and owner.coordination_root != references.root:
            references = DisplayReferences()
        return cls(owner.project_root.resolve(), references)

    def for_source(self, source):
        return LinkContext(self.root, self.references.for_source(source))

    def matches(self, text):
        found = []
        for match in _PATH_PATTERN.finditer(text):
            link = ProjectLink.from_path(self.root, match.group())
            tokens = link.inline_tokens(Token("text", "", 0, content=match.group()))
            if tokens:
                found.append((match.start(), match.end(), tokens))
        for match in self.references.find(text):
            if any(start < match.end and match.start < end for start, end, _ in found):
                continue
            content = Token("text", "", 0, content=text[match.start:match.end])
            found.append((match.start, match.end, OpenReference(match.reference).inline_tokens(content)))
        return sorted(found)


@dataclass(slots=True)
class _ProjectTokens:
    links: LinkContext
    linked: int = 0


class ProjectTokenRule(DeclaredFamily, affix="TokenRule"):
    @classmethod
    def register(cls, parser):
        def native_rule(renderer, tokens, index, options, env):
            return cls.resolve(renderer, tokens[index], env["project_tokens"])
        parser.add_render_rule(FieldCodec.encode(cls), native_rule, fmt=ProjectTokenRenderer.__output__)

    @classmethod
    @abstractmethod
    def resolve(cls, renderer, token, context): ...


class InlineTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer, token, context):
        if token.children is not None:
            token.children = renderer.resolve(token.children, _ProjectTokens(context.links))
        return [token]


class LinkOpenTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer, token, context):
        href = str(token.attrGet("href") or "")
        token.attrSet("href", LineLink.from_href(href).resolved(context.links.root).href)
        context.linked += 1
        return [token]


class LinkCloseTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer, token, context):
        context.linked -= 1
        return [token]


class ImageTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer, token, context):
        # Images are links to a local preview or an external address, never network fetches.
        href = str(token.attrGet("src") or "")
        content = Token("text", "", 0, content=token.content or Path(href).name or "Image")
        if context.linked:
            return [content]
        return LineLink.from_href(href).resolved(context.links.root).inline_tokens(content)


class TextTokenRule(ProjectTokenRule):
    @classmethod
    def resolve(cls, renderer, token, context):
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
    __output__ = "textual-tokens"

    def __init__(self, parser):
        self.rules = {}

    def render(self, tokens, options, env):
        result = []
        for index, token in enumerate(tokens):
            rule = self.rules.get(token.type)
            result.extend(rule(tokens, index, options, env) if rule else (token,))
        return result

    def resolve(self, tokens, context):
        return self.render(tokens, {}, {"project_tokens": context})


class _MarkdownParserState(local):
    def __init__(self):
        self.parser = MarkdownIt("gfm-like", renderer_cls=ProjectTokenRenderer)
        self.parser.validateLink = OpenUrl.opens
        for rule in ProjectTokenRule.members_with(ProjectTokenRule):
            rule.register(self.parser)
        rules = tuple(self.parser.core.ruler.getRules(""))
        boundary = rules.index(inline_rule) + 1
        self.syntax_rules, self.presentation_rules = rules[:boundary], rules[boundary:]


_parser_state = _MarkdownParserState()


def parse_markdown_syntax(source, env=None):
    state = StateCore(source, _parser_state.parser, {} if env is None else env)
    for rule in _parser_state.syntax_rules:
        rule(state)
    return state.tokens


class MessageMarkdownParser:
    def __init__(self, context: LinkContext):
        self.context = context

    def parse(self, source, env=None):
        return self.resolve_tokens(parse_markdown_syntax(source, env))

    def resolve_tokens(self, tokens):
        tokens = _parser_state.parser.renderer.resolve(tokens, _ProjectTokens(self.context))
        state = StateCore("", _parser_state.parser, {}, tokens)
        for rule in _parser_state.presentation_rules:
            rule(state)
        return state.tokens
