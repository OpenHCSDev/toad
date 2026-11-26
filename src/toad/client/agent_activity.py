"""One presentation for agent activity, shared by live and saved sources."""

from collections.abc import Iterable
from dataclasses import replace

from toad.acp.status import ToolCallStatus
from toad.client.line_blocks import (
    NO_LINK,
    Body,
    LineBlock,
    LineLink,
    MarkdownMessageBody,
    Span,
    Summary,
    ThinkingRole,
    ToggleDetails,
    ToolOutputRole,
)
from toad.client.structured_context import ThinkingPart


class AgentActivityPresentation:
    """Construct the rows for thinking, tools and their common group header."""

    group = (Summary.titled("· Agent activity", ThinkingRole),)

    @staticmethod
    def thinking(text: str) -> tuple[LineBlock, ...]:
        return ThinkingPart.from_text(text).line_blocks()

    @staticmethod
    def thinking_blocks(
        text: str,
        *,
        details_open: bool,
        details_link: LineLink = ToggleDetails(),
    ) -> tuple[LineBlock, ...]:
        """Collapsible thinking rows: one tappable summary line when closed, full body when open."""
        part = ThinkingPart.from_text(text)
        if not part.raw_text:
            return ()
        marker = "▼ " if details_open else "▶ "
        title = part.summary_title if details_open else part.label
        header = Summary((Span(f"{marker}{title}", ThinkingRole, details_link),))
        if not details_open:
            return (header,)
        body = MarkdownMessageBody(part.raw_text, role=ThinkingRole, bar=ThinkingRole).presentation()
        return (header, *body)

    @staticmethod
    def tool_has_details(status: ToolCallStatus, details_available: bool) -> bool:
        return len(status.title.splitlines()) > 1 or details_available

    @staticmethod
    def tool(
        status: ToolCallStatus,
        *,
        has_details: bool,
        details_open: bool,
        details: Iterable[LineBlock] = (),
        details_link: LineLink = ToggleDetails(),
    ) -> tuple[LineBlock, ...]:
        title = status.title
        marker = ("▼ " if details_open else "▶ ") if has_details else "· "
        link = details_link if has_details else NO_LINK
        source = status.summary
        summary = Summary((Span(f"{marker}🔧 ", status.summary_role, link),
                           *(replace(span, link=link) for span in source.spans)),
                          kept=tuple(replace(span, link=link) for span in source.kept))
        if not details_open:
            return (summary,)
        return (summary, Body(title, role=ToolOutputRole), *details)
