"""Read-only notification feedback attached to its chat message."""

from rich.text import Text
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Collapsible, Static

from toad.notification_status import (
    DetailLines, NotificationStatus, UnavailableNotifications, UncheckedNotifications,
)
from toad.widgets.transcript_lines import OpensLinks, link_style


class NotificationDetails(OpensLinks, Static):
    """The feedback lines behind a message's notification state; a name opens its thread."""

    def show(self, lines: DetailLines) -> None:
        self.update(Text("\n").join(
            Text.assemble(*((span.text, link_style(span.link)) for span in line)) for line in lines))


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
        self.display = self.status.visible

    def compose(self) -> ComposeResult:
        yield self._title
        if self._details is not None:
            yield self.Contents(self._details)

    @property
    def details(self) -> NotificationDetails:
        """The details body, created only when it is first shown."""
        if self._details is None:
            self._details = NotificationDetails(markup=False)
            if self.is_mounted:
                self.mount(self.Contents(self._details))
        self._details.show(self.status.details)
        return self._details

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            _ = self.details

    def show(self, status: NotificationStatus) -> None:
        if status == self.status:
            return
        self.status = status
        self.display = status.visible
        title = Content(status.title)
        if not title.is_same(Content.from_text(self.title)):
            self.title = title
        if not self.collapsed:
            _ = self.details
        self.set_class(status.working, "-working")
        self.set_class(status.unavailable, "-unavailable")

    def show_error(self, error: Exception) -> None:
        self.show(UnavailableNotifications(str(error)))
