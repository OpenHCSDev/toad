"""Textual-facing: a wire message body becomes one Textual `Content` with emphasis, links and mention spans."""

from agent_comms.mentions import ThreadMention
from toad.line_blocks import OpenTarget, OpenUrl
from toad.widgets.inline_message import inline_message


def meta_at(content, offset):
    return next(span.style.meta for span in content.spans
                if span.start <= offset < span.end and not isinstance(span.style, str) and span.style.meta)


def test_emphasis_code_links_and_mentions_become_spans():
    source = "**Bold** *italic* `x = 1` [docs](https://example.test) and @peer [literal]"
    start = source.index("@peer")
    content = inline_message(source, (ThreadMention("peer", start, start + 5),))
    assert content.plain == "Bold italic x = 1 docs and @peer [literal]"
    assert any(span.start == 0 and span.style == "bold" for span in content.spans)
    assert any(span.start == 5 and span.style == "italic" for span in content.spans)
    assert meta_at(content, content.plain.index("docs"))["@click"] == OpenUrl("https://example.test").click
    assert meta_at(content, content.plain.index("@peer"))["@click"] == OpenTarget("peer").click


def test_unsafe_links_and_plain_text_stay_literal():
    assert inline_message("[link](javascript:alert)").plain == "[link](javascript:alert)"
    # A file is opened, not run: its link is drawn as its label.
    file_link = inline_message("[Open diagnostic](file:///var/tmp/failure.json)")
    assert file_link.plain == "Open diagnostic"
    assert meta_at(file_link, 0)["@click"] == OpenUrl("file:///var/tmp/failure.json").click
    assert inline_message("snake_case remains\nwrapped text").plain == "snake_case remains\nwrapped text"
