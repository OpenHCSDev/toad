"""The existing failure consumer's widget and saved-commit requirements."""
from abc import ABC, abstractmethod

from textual.widget import Widget


class CommitRequirement(ABC):
    @abstractmethod
    def require_commit(self) -> None: ...


class FailurePresentation(ABC):
    """Failure feedback reads this view; it does not replace its transcript."""

    transcript: CommitRequirement

    @abstractmethod
    async def post[WidgetType: Widget](self, widget: WidgetType) -> WidgetType: ...
