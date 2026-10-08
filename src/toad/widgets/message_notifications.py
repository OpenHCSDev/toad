"""Read-only notification feedback attached to its original chat message."""

from collections import Counter

from agent_comms.presentation import MessageNotification
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Collapsible, Static


class MessageNotifications(Collapsible):
    DEFAULT_CSS = """
    MessageNotifications {
        height: auto; padding: 0; margin: 0; border: none;
        background: transparent; color: $text-muted;
        CollapsibleTitle { padding: 0; min-height: 1; }
        Contents { padding: 0 0 0 2; }
        Static { height: auto; }
    }
    MessageNotifications.-working > CollapsibleTitle { color: $accent; }
    MessageNotifications.-unavailable > CollapsibleTitle { color: $warning; }
    """

    def __init__(self) -> None:
        self._notifications: tuple[MessageNotification, ...] | None = None
        self._error: str | None = None
        self._details: Static | None = None
        super().__init__(title="Notification status not checked", collapsed=True)

    def compose(self) -> ComposeResult:
        yield self._title
        if self._details is not None:
            yield self.Contents(self._details)

    @property
    def details(self) -> Static:
        """Acquire the original disclosure body only when it is requested."""
        if self._details is None:
            self._details = Static(markup=False)
            if self.is_mounted:
                self.mount(self.Contents(self._details))
        self._details.update(self._detail_text())
        return self._details

    def _detail_text(self) -> str:
        if self._error is not None:
            return f"Could not check notification status: {self._error}"
        if self._notifications is None:
            return "Not checked yet"
        return "\n".join(
            f"{item.recipient}: {item.state}"
            + (f" — {item.detail}" if item.detail else "")
            for item in sorted(self._notifications, key=lambda item: (item.priority, item.recipient.casefold()))
        ) or "No notification result is recorded for this message. This does not confirm receipt."

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            _ = self.details

    def show_result(self, notifications: tuple[MessageNotification, ...]) -> None:
        if self._error is None and self._notifications == notifications:
            return
        self._notifications, self._error = notifications, None
        ordered = sorted(notifications, key=lambda item: (item.priority, item.recipient.casefold()))
        counts = Counter(item.state for item in ordered)
        states = list(counts)
        summary = " · ".join(f"{state} ({counts[state]})" for state in states[:3])
        if len(states) > 3:
            summary += f" · {sum(counts[state] for state in states[3:])} others"
        title = Content(summary or "No recorded notification result")
        if not title.is_same(Content.from_text(self.title)):
            self.title = title
        if not self.collapsed:
            _ = self.details
        self.set_class(any(item.busy for item in notifications), "-working")
        self.remove_class("-unavailable")

    def show_error(self, error: Exception) -> None:
        detail = str(error)
        if self._error == detail:
            return
        self._notifications, self._error = None, detail
        title = Content("Notification status unavailable")
        if not title.is_same(Content.from_text(self.title)):
            self.title = title
        if not self.collapsed:
            _ = self.details
        self.remove_class("-working")
        self.add_class("-unavailable")
