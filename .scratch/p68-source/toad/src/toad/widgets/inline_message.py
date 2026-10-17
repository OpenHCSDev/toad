"""Inline message formatting as Textual content, from the shared span parser."""

from __future__ import annotations
from typing import TYPE_CHECKING
from textual.content import Content
from textual.style import Style

from toad.inline_spans import inline_spans

if TYPE_CHECKING:
    from toad.textual_colours import TextualColours


def inline_message(body: str, colours: TextualColours, context) -> Content:
    result = Content("")
    for span in inline_spans(body, context):
        part = Content.styled(span.text, colours.style(span.role))
        if span.link is not None:
            part = part.stylize(Style.from_meta({"@click": span.link.click}))
        result += part
    return result
