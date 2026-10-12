"""Read-only notification feedback attached to its chat message."""

from agent_comms.presentation import MessageNotification
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Collapsible, Static

from toad.notification_status import (
    CheckedNotifications, NotificationStatus, UnavailableNotifications, UncheckedNotifications,
)


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
        self.status: NotificationStatus = UncheckedNotifications()
        self._details: Static | None = None
        super().__init__(title=self.status.title, collapsed=True)

    def compose(self) -> ComposeResult:
        yield self._title
        if self._details is not None:
            yield self.Contents(self._details)

    @property
    def details(self) -> Static:
        """The details body, created only when it is first shown."""
        if self._details is None:
            self._details = Static(markup=False)
            if self.is_mounted:
                self.mount(self.Contents(self._details))
        self._details.update(self.status.details)
        return self._details

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            _ = self.details

    def show(self, status: NotificationStatus) -> None:
        if status == self.status:
            return
        self.status = status
        title = Content(status.title)
        if not title.is_same(Content.from_text(self.title)):
            self.title = title
        if not self.collapsed:
            _ = self.details
        self.set_class(status.working, "-working")
        self.set_class(status.unavailable, "-unavailable")

    def show_result(self, notifications: tuple[MessageNotification, ...]) -> None:
        self.show(CheckedNotifications(notifications))

    def show_error(self, error: Exception) -> None:
        self.show(UnavailableNotifications(str(error)))
