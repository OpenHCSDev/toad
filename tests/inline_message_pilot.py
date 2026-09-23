"""IRC stays one wrapping text widget while formatting and mention links survive."""

from agent_comms.mentions import ThreadMention
from toad.widgets.inline_message import inline_message


def check():
    source = "**Bold** *italic* `x = 1` [docs](https://example.test) and @peer [literal]"
    start = source.index("@peer")
    content = inline_message(source, (ThreadMention("peer", start, start + 5),))
    assert content.plain == "Bold italic x = 1 docs and @peer [literal]"
    assert any(span.start == 0 and span.style == "bold" for span in content.spans)
    assert any(span.start == 5 and span.style == "italic" for span in content.spans)
    def meta_at(offset):
        return next(span.style.meta for span in content.spans
                    if span.start <= offset < span.end and not isinstance(span.style, str)
                    and span.style.meta)
    assert meta_at(content.plain.index("docs"))["@click"] == (
        "open_url", ("https://example.test",)
    )
    assert meta_at(content.plain.index("@peer"))["@click"] == (
        "open_target", ("peer",)
    )
    assert inline_message("[link](javascript:alert)").plain == "[link](javascript:alert)"
    assert inline_message("snake_case remains\nwrapped text").plain == "snake_case remains\nwrapped text"
    print("inline IRC: emphasis/code/links, exact mention-offset projection, literal text and compact flow")


if __name__ == "__main__":
    check()
