"""Inline message formatting as Textual content, from the shared span parser."""

from textual.content import Content
from textual.style import Style

from toad.inline_spans import inline_spans
from toad.line_blocks import (
    CodeRole, EmphasisRole, LineRole, MentionRole, StrongRole, TextRole, UrlRole,
)

_STYLES: dict[type[LineRole], str] = {
    TextRole: "", StrongRole: "bold", EmphasisRole: "italic", CodeRole: "$text-accent",
    UrlRole: "$accent underline", MentionRole: "$accent bold",
}


def inline_message(body: str, mentions=()) -> Content:
    result = Content("")
    for span in inline_spans(body, mentions):
        part = Content.styled(span.text, _STYLES[span.role])
        if span.link is not None:
            part = part.stylize(Style.from_meta({"@click": span.link.click}))
        result += part
    return result
