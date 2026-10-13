"""One presentation for agent activity, shared by live and saved sources."""

from collections.abc import Iterable

from toad.acp.status import ToolCallStatus
from toad.line_blocks import Body, Gap, LineBlock, Summary, ThinkingRole, ToggleDetails
from toad.widgets.message_filter import MessageCategory


class AgentActivityPresentation:
    """Construct the rows for thinking, tools and their common group header."""

    group = (Summary("· Agent activity"),)

    @staticmethod
    def thinking(text: str, *, complete: bool = True) -> tuple[LineBlock, ...]:
        rows: tuple[LineBlock, ...] = (Body(text, role=ThinkingRole),)
        return (*rows, Gap()) if complete else rows

    @staticmethod
    def tool_has_details(status: ToolCallStatus, details_available: bool) -> bool:
        return len((status.call.title or "Tool").splitlines()) > 1 or details_available

    @staticmethod
    def tool(
        status: ToolCallStatus,
        *,
        has_details: bool,
        details_open: bool,
        details: Iterable[LineBlock] = (),
    ) -> tuple[LineBlock, ...]:
        title = status.call.title or "Tool"
        marker = ("▼ " if details_open else "▶ ") if has_details else "· "
        summary = Summary(f"{marker}🔧 {title}{status.summary_suffix}", link=(
            ToggleDetails() if has_details else None
        ))
        if not details_open:
            return (summary,)
        return (summary, Body(title, markdown=False), *details)


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
