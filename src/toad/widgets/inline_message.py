"""Inline message formatting as Textual content, from the shared span parser."""

from __future__ import annotations
from typing import TYPE_CHECKING
from textual.content import Content
from textual.style import Style

from metaclass_registry.mro_dispatch import handles

from toad.core.projection import MroProjection
from toad.inline_spans import inline_spans
from toad.link_click import OpenLineLink
from toad.line_blocks import LineLink, NoLink

if TYPE_CHECKING:
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


def inline_message(body: str, colours: TextualColours, context) -> Content:
    result = Content("")
    for span in inline_spans(body, context):
        result += INLINE_LINK.project_value(span.link, Content.styled(span.text, colours.style(span.role)))
    return result
