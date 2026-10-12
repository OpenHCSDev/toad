"""Inline message formatting as spans: emphasis, code, links and mentions, no Markdown tree."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from toad.line_blocks import (
    CodeRole, EmphasisRole, LineLink, LineRole, MentionRole, OpenTarget, OpenUrl, Span,
    StrongRole, TextRole, UrlRole,
)

_INLINE = re.compile(
    r"(?<!\\)(?:`(?P<code>[^`\n]+)`|\*\*(?P<strong>[^\n]+?)\*\*|"
    r"__(?P<strong_under>[^\n]+?)__|\*(?P<em>[^*\n]+)\*|"
    r"(?<!\w)_(?P<em_under>[^_\n]+)_(?!\w)|"
    r"\[(?P<label>[^\]\n]+)\]\((?P<url>[^\s)]+)\))"
)
_ROLES = {"code": CodeRole, "strong": StrongRole, "strong_under": StrongRole,
          "em": EmphasisRole, "em_under": EmphasisRole}


def inline_spans(body: str, mentions=()) -> tuple[Span, ...]:
    """The body's spans in order; a mention inside one piece of text becomes its own span."""
    # Each piece keeps where it came from in the body: mention offsets are
    # positions in the body, before delimiters and URL targets were removed.
    pieces: list[tuple[int, int, type[LineRole], LineLink | None]] = []
    position = 0
    for match in _INLINE.finditer(body):
        pieces.append((position, match.start(), TextRole, None))
        name = match.lastgroup if match.lastgroup != "url" else "label"
        if name in _ROLES:
            pieces.append((*match.span(name), _ROLES[name], None))
        elif urlsplit(match.group("url")).scheme.lower() in {"http", "https", "mailto"}:
            pieces.append((*match.span("label"), UrlRole, OpenUrl(match.group("url"))))
        else:
            pieces.append((match.start(), match.end(), TextRole, None))
        position = match.end()
    pieces.append((position, len(body), TextRole, None))
    for mention in mentions:
        for index, (start, end, role, link) in enumerate(pieces):
            if start <= mention.start and mention.end <= end:
                pieces[index:index + 1] = [
                    (start, mention.start, role, link),
                    (mention.start, mention.end, MentionRole, OpenTarget(mention.thread)),
                    (mention.end, end, role, link),
                ]
                break
    return tuple(Span(body[start:end], role, link) for start, end, role, link in pieces if end > start)
