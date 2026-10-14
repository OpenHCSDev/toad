"""One presentation for agent activity, shared by live and saved sources."""

from collections.abc import Iterable
from dataclasses import replace

from toad.acp.status import ToolCallStatus
from toad.line_blocks import Body, Gap, LineBlock, Span, Summary, ThinkingRole, ToggleDetails, ToolOutputRole
from toad.widgets.message_filter import MessageCategory


class AgentActivityPresentation:
    """Construct the rows for thinking, tools and their common group header."""

    group = (Summary.titled("· Agent activity", ThinkingRole),)

    @staticmethod
    def thinking(text: str, *, complete: bool = True) -> tuple[LineBlock, ...]:
        rows: tuple[LineBlock, ...] = (Body(text, role=ThinkingRole),)
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
    ) -> tuple[LineBlock, ...]:
        title = status.title
        marker = ("▼ " if details_open else "▶ ") if has_details else "· "
        link = ToggleDetails() if has_details else None
        summary = Summary((Span(f"{marker}🔧 ", status.summary_role, link),
                           *(replace(span, link=link) for span in status.summary_spans)))
        if not details_open:
            return (summary,)
        return (summary, Body(title, role=ToolOutputRole, markdown=False), *details)


class AgentActivityBoundary:
    """Thinking/tool output needs a role header if no agent content precedes it.

    This is display grouping only. It does not infer or control execution turns.
    Ordinary reply/routing headers remain owned by their message widgets.
    """

    def __init__(self) -> None:
        self._pending = True

    def reset(self) -> None:
        self._pending = True

    def observe(self, category: type[MessageCategory] | None) -> bool:
        return category.observe(self) if category is not None else False
