"""Read-only notification feedback attached to its original chat message."""

from collections import Counter

from agent_comms.presentation import MessageNotification
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
        self.details = Static("Not checked yet", markup=False)
        super().__init__(self.details, title="Notification status not checked", collapsed=True)

    def show_result(self, notifications: tuple[MessageNotification, ...]) -> None:
        ordered = sorted(notifications, key=lambda item: (item.priority, item.recipient.casefold()))
        counts = Counter(item.state for item in ordered)
        states = list(counts)
        summary = " · ".join(f"{state} ({counts[state]})" for state in states[:3])
        if len(states) > 3:
            summary += f" · {sum(counts[state] for state in states[3:])} others"
        self.title = Content(summary or "No recorded notification result")
        self.details.update("\n".join(
            f"{item.recipient}: {item.state}"
            + (f" — {item.detail}" if item.detail else "")
            for item in ordered
        ) or "No notification result is recorded for this message. This does not confirm receipt.")
        self.set_class(any(item.busy for item in notifications), "-working")
        self.remove_class("-unavailable")

    def show_error(self, error: Exception) -> None:
        self.title = Content("Notification status unavailable")
        self.details.update(f"Could not check notification status: {error}")
        self.remove_class("-working")
        self.add_class("-unavailable")
