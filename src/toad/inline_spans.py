"""The shared Markdown tokens laid out inline instead of as block Markdown."""
from abc import abstractmethod
from dataclasses import dataclass, field

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import FieldCodec

from toad.line_blocks import NO_LINK, CodeRole, EmphasisRole, LineLink, Span, StrongRole, TextRole
from toad.markdown_links import MessageMarkdownParser


@dataclass
class InlineSpans:
    roles: list = field(default_factory=lambda: [TextRole])
    links: list[LineLink] = field(default_factory=lambda: [NO_LINK])
    spans: list = field(default_factory=list)

    def text(self, text, role=None):
        link = self.links[-1]
        self.spans.append(Span(text, link.text_role(role or self.roles[-1]), link))

    def consume(self, tokens):
        rules = {FieldCodec.encode(rule): rule for rule in InlineSpanRule.members_with(InlineSpanRule)}
        for token in tokens:
            if token.children:
                self.consume(token.children)
            elif (rule := rules.get(token.type)) is not None:
                rule.apply(token, self)


class InlineSpanRule(DeclaredFamily, affix="SpanRule"):
    @classmethod
    @abstractmethod
    def apply(cls, token, state): ...


class TextSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.text(token.content)


class CodeInlineSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.text(token.content, CodeRole)


class LinkOpenSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.links.append(token.attrGet("href").target)


class LinkCloseSpanRule(InlineSpanRule):
    @classmethod
    def apply(cls, token, state):
        state.links.pop()


class StyleOpenSpanRule(InlineSpanRule):
    role = None

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
