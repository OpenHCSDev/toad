"""Inline message formatting as Textual content, from the shared span parser."""

from __future__ import annotations

from collections.abc import Iterable

from textual.content import Content
from textual.style import Style

from metaclass_registry.mro_dispatch import handles

from toad.core.projection import MroProjection
from toad.inline_spans import inline_spans
from toad.link_click import OpenLineLink
from toad.client.line_blocks import LineLink, NoLink, Span
from toad.textual_colours import TextualColours


class InlineLink(MroProjection[Content]):
    """A span that leads somewhere runs its action when clicked; plain text stays as styled."""

    @handles(LineLink)
    def linked(self, link: LineLink, part: Content) -> Content:
        return part.stylize(Style.from_meta({"@click": OpenLineLink(link)}))

    @handles(NoLink)
    def plain(self, link: NoLink, part: Content) -> Content:
        return part


INLINE_LINK = InlineLink()


def span_content(spans: Iterable[Span], colours: TextualColours) -> Content:
    """Shared spans drawn as Textual content, each in its role's resolved style."""
    result = Content("")
    for span in spans:
        result += INLINE_LINK.project_value(span.link, Content.styled(span.text, colours.style(span.role)))
    return result


def inline_message(body: str, colours: TextualColours, context) -> Content:
    return span_content(inline_spans(body, context), colours)
