"""Toad's line blocks as Qt rich text: the blocks RichLineRenderer paints for Textual,
in the same roles and the same theme colours."""

from __future__ import annotations

from html import escape

from agent_comms.storage.recorded_time import RecordedEventTime, UnrecordedEventTime
from markdown_it import MarkdownIt
from metaclass_registry.mro_dispatch import handles
from ui_theme.scheme import ColourScheme

from toad.client.line_blocks import Body, Divider, LineBlock, LineRole, NoBar, Span, Spans
from toad.core.projection import MroProjection
from toad.message_rows import RecordedMessageClock, WireBody


class QtDividerTime(MroProjection[str]):
    """A recorded divider shows its time after the title; an unrecorded one shows none."""

    @handles(RecordedEventTime)
    def recorded(self, time: RecordedEventTime) -> str:
        return f" · {RecordedMessageClock(time.at).display()[0]}"

    @handles(UnrecordedEventTime)
    def unrecorded(self, time: UnrecordedEventTime) -> str:
        return ""


QT_DIVIDER_TIME = QtDividerTime()


class QtLineRenderer(MroProjection[str]):
    """Each block through its most specific declared painter, as a fragment of Qt rich text."""

    def __init__(self, scheme: ColourScheme) -> None:
        self.scheme = scheme
        self.markdown = MarkdownIt("commonmark", {"breaks": True})

    def colour(self, role: type[LineRole]) -> str:
        return role.colour.rgb(self.scheme).hex

    def styled(self, text: str, role: type[LineRole]) -> str:
        css = [f"color:{self.colour(role)}"]
        css += ["font-weight:bold"] * role.bold + ["font-style:italic"] * role.italic
        css += ["text-decoration:underline"] * role.underline
        return f'<span style="{";".join(css)}">{escape(text)}</span>'

    def span(self, span: Span, role: type[LineRole]) -> str:
        return self.styled(span.text, role)

    def html(self, blocks: tuple[LineBlock, ...]) -> str:
        return "".join(self.project_value(block) for block in blocks)

    @handles(Divider)
    def divider(self, block: Divider) -> str:
        title = "".join(self.span(span, span.link.heading_role(span.role, block.role)) for span in block.spans)
        rule = self.colour(block.role)
        return (f'<table width="100%" cellspacing="0" cellpadding="4" style="margin-top:10px">'
                f'<tr><td style="border-top:1px solid {rule}"><b>{title}</b>'
                f'{self.styled(QT_DIVIDER_TIME.project_value(block.timestamp), block.role)}</td></tr></table>')

    @handles(Spans)
    def spans(self, block: Spans) -> str:
        return "<p>" + "".join(self.span(span, span.role) for span in block.spans) + "</p>"

    @handles(WireBody)
    def wire_body(self, block: WireBody) -> str:
        return self.body(Body(block.text, bar=block.bar))

    @handles(Body)
    def body(self, block: Body) -> str:
        text = f'<div style="color:{self.colour(block.role)}">{self.markdown.render(block.text)}</div>'
        if block.bar is NoBar:
            return text
        return (f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                f'<td width="3" style="background-color:{self.colour(block.bar)}"></td>'
                f'<td style="padding-left:8px">{text}</td></tr></table>')
