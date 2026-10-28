"""One presentation for agent activity, shared by live and saved sources."""

from collections.abc import Iterable
from dataclasses import replace

from toad.acp.status import ToolCallStatus
from toad.line_blocks import Body, MarkdownBody, Gap, LineBlock, LineLink, Span, Summary, ThinkingRole, ToggleDetails, ToolOutputRole


class AgentActivityPresentation:
    """Construct the rows for thinking, tools and their common group header."""

    group = (Summary.titled("· Agent activity", ThinkingRole),)

    @staticmethod
    def thinking(text: str, *, complete: bool = True) -> tuple[LineBlock, ...]:
        rows: tuple[LineBlock, ...] = (MarkdownBody(text, role=ThinkingRole),)
        return (*rows, Gap()) if complete else rows

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
        link = details_link if has_details else None
        source = status.summary
        summary = Summary((Span(f"{marker}🔧 ", status.summary_role, link),
                           *(replace(span, link=link) for span in source.spans)),
                          kept=tuple(replace(span, link=link) for span in source.kept))
        if not details_open:
            return (summary,)
        return (summary, Body(title, role=ToolOutputRole), *details)
