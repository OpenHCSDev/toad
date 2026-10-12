"""Textual-facing: a wire message's lines wrap at the full width as Rich draws them, and its names stay clickable at every width."""

from agent_comms.messages import Message, MessageType
from textual.app import App

from toad.line_blocks import OpenTarget
from toad.widgets.transcript_lines import LineTheme, PlainLines, PlainRowCount, RichLineRenderer
from toad.wire_history import IrcMessageStyle, MarkdownMessageStyle, MessageFragment, Shown


def fragment(target, style=IrcMessageStyle()):
    message = Message(sender="explorer-grandchild", target=target,
                      body="payload " * 30 + "\nsecond paragraph [literal markup]", type=MessageType.INFO)
    return MessageFragment((message,), shown=Shown(style), evidence=None, direction="Inbound")


def theme():
    return LineTheme.of(App().get_css_variables(), "truecolor")


def clicks(rows):
    return {segment.style.meta["@click"] for row in rows for segment in row
            if segment.style is not None and "@click" in segment.style.meta}


def test_rows_fit_the_width_wrap_on_words_and_keep_their_names_clickable_at_every_width():
    for target in ("#all", "receiver-with-long-name"):
        shown = fragment(target)
        for width in (80, 36, 120):
            rows = RichLineRenderer(theme(), width).rows(shown.line_blocks)
            text = ["".join(segment.text for segment in row) for row in rows]
            assert all(len(line) <= width for line in text), (width, text)
            # Gap, caption, the wrapped text, then the notification line.
            body = text[2:-1]
            words = [line.split() for line in body[:-1]]
            assert sum(words, []) == ["explorer-grandchild", "→", target, *["payload"] * 30], (width, body)
            assert body[-1].rstrip() == "second paragraph [literal markup]", (width, body)
            assert {OpenTarget("explorer-grandchild").click, OpenTarget(target).click} <= clicks(rows)
            assert ("open_target", (target,)) in clicks(rows)


def test_the_rows_that_count_as_reading_are_the_text_between_caption_and_notification_line():
    for style in (IrcMessageStyle(), MarkdownMessageStyle()):
        shown = fragment("#all", style)
        for width in (36, 80):
            lines = PlainLines(width, theme(), shown.line_blocks)
            assert lines.height == len(lines.rows) == PlainRowCount(width).height(shown.line_blocks)
            rows = shown.text_rows(lines)
            assert (rows.start, rows.stop) == (2, lines.height - 1)
            # With its details open the notification takes more rows below the text.
            opened = fragment("#all", style)
            opened.show(Shown(style, details_open=True))
            taller = PlainLines(width, theme(), opened.line_blocks)
            assert opened.text_rows(taller) == rows and taller.height > lines.height
