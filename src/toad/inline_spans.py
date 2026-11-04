"""The shared Markdown tokens laid out inline instead of as block Markdown."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import FieldCodec

from toad.line_blocks import NO_LINK, CodeRole, EmphasisRole, LineLink, LineRole, Span, StrongRole, TextRole
from toad.markdown_links import MessageMarkdownParser


@dataclass
class InlineSpans:
    roles: list = field(default_factory=lambda: [TextRole])
    links: list[LineLink] = field(default_factory=lambda: [NO_LINK])
    spans: list = field(default_factory=list)

    def text(self, text):
        """Text in the surrounding emphasis."""
        self.styled(text, self.roles[-1])

    def styled(self, text, role: type[LineRole]):
        link = self.links[-1]
        self.spans.append(Span(text, link.text_role(role), link))

    def consume(self, tokens):
        for token in tokens:
            if token.children:
                self.consume(token.children)
            else:
                InlineSpanRule.for_token(token.type).apply(token, self)


class InlineSpanRule(DeclaredFamily, affix="SpanRule"):
    @classmethod
    def apply(cls, token, state):
        """A token kind with no rule of its own adds nothing to the line."""

    @classmethod
    @cache
    def for_token(cls, token_type: str) -> type[InlineSpanRule]:
        """Decode a parser token kind once: its declared rule, or the family's do-nothing default."""
        return {FieldCodec.encode(rule): rule for rule in cls.members_with(cls)}.get(token_type, cls)


class TextSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.text(token.content)


class CodeInlineSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.styled(token.content, CodeRole)


class LinkOpenSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.links.append(token.attrGet("href").target)


class LinkCloseSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.links.pop()


class StyleOpenSpanRule(InlineSpanRule, declared_name=None):
    role: ClassVar[type[LineRole]]

    @classmethod
    def apply(cls, token, state):
        state.roles.append(cls.role)


class StrongOpenSpanRule(StyleOpenSpanRule):
    role = StrongRole


class EmOpenSpanRule(StyleOpenSpanRule):
    role = EmphasisRole


class StrongCloseSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.roles.pop()


class EmCloseSpanRule(StrongCloseSpanRule):
    pass


class HardbreakSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.text("\n")


class SoftbreakSpanRule(HardbreakSpanRule):
    pass


def inline_spans(body, context):
    state = InlineSpans()
    state.consume(MessageMarkdownParser(context).parse_inline(body))
    return tuple(state.spans)
