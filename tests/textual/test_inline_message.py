"""A wire message body becomes inline spans with emphasis, code and typed links."""

from agent_comms.display_references import ProjectReferences
from toad.inline_spans import inline_spans
from toad.line_blocks import CodeRole, EmphasisRole, StrongRole, TextRole, UrlRole
from toad.markdown_links import LinkContext
from toad.project_link import ExternalProjectLink


def test_emphasis_code_and_links_become_spans(tmp_path):
    spans = inline_spans("**Bold** *italic* `x = 1` [docs](https://example.test) [literal]",
                         LinkContext(tmp_path, ProjectReferences()))
    assert "".join(span.text for span in spans) == "Bold italic x = 1 docs [literal]"
    roles = {span.text: span.role for span in spans}
    assert (roles["Bold"], roles["italic"], roles["x = 1"], roles["docs"]) == (
        StrongRole, EmphasisRole, CodeRole, UrlRole)
    assert next(span.link for span in spans if span.text == "docs") == ExternalProjectLink("https://example.test")


def test_unsafe_links_and_plain_text_stay_literal(tmp_path):
    context = LinkContext(tmp_path, ProjectReferences())
    unsafe = inline_spans("[link](javascript:alert)", context)
    assert "".join(span.text for span in unsafe) == "[link](javascript:alert)"
    assert all(span.link is None and span.role is TextRole for span in unsafe)
    plain = inline_spans("snake_case remains\nwrapped text", context)
    assert "".join(span.text for span in plain) == "snake_case remains\nwrapped text"
