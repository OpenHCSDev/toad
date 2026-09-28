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

    def observe(self, category: type[MessageCategory] | None) -> bool:
        return category.observe(self) if category is not None else False
