"""Inline message formatting without building a Markdown widget tree."""

import re
from urllib.parse import urlsplit

from textual.content import Content
from textual.style import Style

_INLINE = re.compile(
    r"(?<!\\)(?:`(?P<code>[^`\n]+)`|\*\*(?P<strong>[^\n]+?)\*\*|"
    r"__(?P<strong_under>[^\n]+?)__|\*(?P<em>[^*\n]+)\*|"
    r"(?<!\w)_(?P<em_under>[^_\n]+)_(?!\w)|"
    r"\[(?P<label>[^\]\n]+)\]\((?P<url>[^\s)]+)\))"
)


def inline_message(body: str, mentions=()) -> Content:
    result = Content("")
    # Source-to-display intervals keep authoritative mention offsets correct
    # after formatting delimiters and URL targets have been removed.
    intervals: list[tuple[int, int, int]] = []

    def append(start: int, end: int, style: str = "", url: str | None = None):
        nonlocal result
        intervals.append((start, end, len(result)))
        part = Content.styled(body[start:end], style)
        if url:
            part = part.stylize(Style.from_meta({"@click": ("open_url", (url,))}))
        result += part

    position = 0
    for match in _INLINE.finditer(body):
        append(position, match.start())
        if match.group("code") is not None:
            append(*match.span("code"), "$text-accent")
        elif (name := next((name for name in ("strong", "strong_under", "em", "em_under")
                           if match.group(name) is not None), None)) is not None:
            append(*match.span(name), "bold" if name.startswith("strong") else "italic")
        elif urlsplit(match.group("url")).scheme.lower() in {"http", "https", "mailto"}:
            append(*match.span("label"), "$accent underline", url=match.group("url"))
        else:
            append(match.start(), match.end())
        position = match.end()
    append(position, len(body))
    for mention in mentions:
        for start, end, displayed in intervals:
            if start <= mention.start and mention.end <= end:
                left, right = displayed + mention.start - start, displayed + mention.end - start
                result = result.stylize("$accent bold", left, right).stylize(
                    Style.from_meta({"@click": ("open_target", (mention.thread,))}), left, right
                )
                break
    return result
