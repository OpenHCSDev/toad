"""Presentation boundaries shared by live output and saved transcript fragments."""

from toad.widgets.message_filter import MessageCategory


class AgentActivityBoundary:
    """Thinking/tool output needs a role header if no agent content precedes it.

    This is display grouping only. It does not infer or control execution turns.
    Ordinary reply/routing headers remain owned by their message widgets.
    """

    def __init__(self) -> None:
        self._pending = True

    def reset(self) -> None:
        self._pending = True

    def observe(self, category: MessageCategory | None) -> bool:
        if category in {MessageCategory.USER, MessageCategory.INBOUND}:
            self.reset()
        elif category in {MessageCategory.AGENT, MessageCategory.OUTBOUND}:
            self._pending = False
        elif category in {MessageCategory.THINKING, MessageCategory.TOOL}:
            show = self._pending
            self._pending = False
            return show
        return False
