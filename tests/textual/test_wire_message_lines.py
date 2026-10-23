"""Textual-facing: a wire message's lines wrap at the full width as Rich draws them, and its names stay clickable at every width."""

from agent_comms.display_references import ProjectReferences
from agent_comms.messages import InfoKind, Message
from textual.app import App

from toad.line_blocks import OpenTarget, ToggleDetails
from toad.markdown_links import LinkContext
from toad.notification_status import CheckedNotifications
from toad.textual_colours import ThemedApp
from toad.widgets.transcript_lines import LinePreparation, PlainLines, RichLineRenderer, TranscriptLinesRenderTask
from toad.message_rows import IrcMessageStyle, MarkdownMessageStyle
from toad.widgets.transcript_fragments import MessageShown
from toad.wire_history import WireFragment


class MessageApp(ThemedApp, App):
    pass


def fragment(target, style=IrcMessageStyle()):
    message = Message(sender="explorer-grandchild", target=target,
                      body="payload " * 30 + "\nsecond paragraph [literal markup]", type=InfoKind)
    return WireFragment.of(message, shown=MessageShown(style=style), evidence=None, reader="reader")


def theme():
    app = MessageApp()
    app.get_css_variables()
    return app.colours.line_theme


def clicks(rows):
    return {segment.style.meta["@click"] for row in rows for segment in row
            if segment.style is not None and "@click" in segment.style.meta}


def test_rows_fit_the_width_wrap_on_words_and_keep_drawn_names_clickable_at_every_width(tmp_path):
    context = LinkContext(tmp_path, ProjectReferences())
    for target in ("#all", "receiver-with-long-name"):
        shown = fragment(target)
        renderer = RichLineRenderer(theme())
        prepared = TranscriptLinesRenderTask(LinePreparation(shown.line_blocks, renderer.theme), context).execute()
        for width in (80, 36, 120):
            lines = prepared.wrap(width, renderer)
            rows = tuple(lines)
            text = ["".join(segment.text for segment in row) for row in rows]
            assert all(len(line) <= width for line in text), (width, text)
            body = [text[index] for index in shown.text_rows(lines)]
            words = [line.split() for line in body[:-1]]
            assert sum(words, []) == ["payload"] * 30, (width, body)
            assert body[-1].rstrip() == "second paragraph [literal markup]", (width, body)
            names = (shown.message.sender, target)
            drawn = "\n".join(text)
            if width >= 80:
                assert all(name in drawn for name in names), (width, text)
            expected = {OpenTarget(name).click for name in names if name in drawn}
            actual = clicks(rows) - {ToggleDetails().click}
            assert actual == expected, (width, text, actual, expected)


def test_opening_notification_details_draws_more_rows_than_the_collapsed_message():
    status = CheckedNotifications(())
    for style in (IrcMessageStyle(), MarkdownMessageStyle()):
        shown = fragment("#all", style)
        shown.show(MessageShown(style=style, status=status))
        for width in (36, 80):
            lines = PlainLines(width, RichLineRenderer(theme()), shown.line_blocks)
            opened = fragment("#all", style)
            opened.show(MessageShown(style=style, status=status, details_open=True))
            taller = PlainLines(width, RichLineRenderer(theme()), opened.line_blocks)
            assert taller.height > lines.height
