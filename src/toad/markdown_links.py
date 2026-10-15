"""One syntax and link resolver for line, inline and Textual Markdown views."""
from __future__ import annotations

import re
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import local

from agent_comms.declared_family import DeclaredFamily
from agent_comms.display_references import ReferenceContext, ProjectReferences
from agent_comms.mro_dispatch import handles
from toad.core.events import LinkContextChanged
from toad.core_event_carrier import CoreEventReceiver
from agent_comms.field_codec import FieldCodec
from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore, inline as inline_rule
from markdown_it.token import Token

from toad.line_blocks import LineLink, LinkHref, OpenReference
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
    references: ReferenceContext

    @classmethod
    async def acquire(cls, widget):
        from toad.project_path_owner import ProjectPathOwner
        owner = ProjectPathOwner.containing(widget)
        root, coordination = owner.project_root.resolve(), owner.coordination_root
        references = (ProjectReferences() if coordination is None else
                      await widget.app.coordination_access.current_references(coordination))
        return cls(root, references)

    @classmethod
    def containing(cls, widget):
        from toad.project_path_owner import ProjectPathOwner
        owner = ProjectPathOwner.containing(widget)
        references = (ProjectReferences() if owner.coordination_root is None else
                      widget.app.coordination_access.reference_context(owner.coordination_root))
        return cls(owner.project_root.resolve(), references)

    def current_for(self, widget):
        return self == self.containing(widget)

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


class ReferenceRendering(CoreEventReceiver):
    """Borrow the source's observation for exactly this rendering lifetime."""
    def _on_mount(self):
        from toad.project_path_owner import ProjectPathOwner
        owner = ProjectPathOwner.containing(self)
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(owner.link_context_events)
        self.app.coordination_access.show_references(self, owner.coordination_root is not None)

    def _on_unmount(self):
        try:
            self.app.coordination_access.show_references(self, False)
        finally:
            super()._on_unmount()

    @handles(LinkContextChanged)
    def reference_context_changed(self, message):
        from toad.project_path_owner import ProjectPathOwner
        owner = ProjectPathOwner.containing(self)
        self.app.coordination_access.show_references(self, owner.coordination_root is not None)
        self.invalidate_lines()

    @abstractmethod
    def invalidate_lines(self, change=None): ...


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
        target = ProjectLink.from_href(lambda: context.links.root, href)
        token.meta["link"] = target
        token.attrSet("href", LinkHref.capture(target))
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
        return LineLink.inline_tokens(ProjectLink.from_href(lambda: context.links.root, href), content)


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
        self.parser.validateLink = ProjectLink.opens
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
