"""Show queued messages, their delivery status and available actions."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.css.native import NativeDeclaration, Variable
from textual.css.styles import Styles
from ui_theme.scheme import ErrorColour
from textual.widgets import Static

from toad.widgets.acting_button import ActingButton, DismissButton
from toad.client.queue_inspection import QueueInspectionOwner
from toad.conversation_submission import ConversationSubmissions
from toad.native_style import AutoHeight
from toad.screens.modal import CenteredScreen, ShadedScreen, SurfacePanel
from toad.screens.source_modal import SourceModal

from toad.widgets.tool_content import ToolContent

class QueuePanel(SurfacePanel):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = "85%"
        self.styles.max_width = 110
        self.styles.height = "75%"
        self.styles.padding = (1, 2)


class QueueError(AutoHeight, Static):
    native_theme = (NativeDeclaration.of(Styles.color, Variable(ErrorColour.name)),)



class QueueActions(AutoHeight, HorizontalGroup):
    """Its look is its bases."""


class QueueSendNow(ActingButton):
    """Delivers the queued inputs now."""

    async def act(self) -> None:
        await self.query_ancestor(QueueInspection).send_now()


class QueueClear(ActingButton):
    """Discards the queued inputs."""

    async def act(self) -> None:
        await self.query_ancestor(QueueInspection).clear_queue()


class QueueInspection(QueueInspectionOwner, ShadedScreen, CenteredScreen, SourceModal):
    """Shows the selected conversation's queue and delivery status; `QueueInspectionOwner`
    owns the reading and the actions, shared with Qt's `QtQueueInspection`."""

    def __init__(self, submissions: ConversationSubmissions) -> None:
        super().__init__()
        self.inspect_submissions(submissions)

    @property
    def source_view(self):
        return self.submissions.view

    def compose(self) -> ComposeResult:
        with QueuePanel():
            yield Static(self.heading)
            with VerticalScroll():
                details = ToolContent()
                details.update((self.details_block(),))
                yield details
            yield Static(self.unavailable_note)
            yield QueueError("")
            with QueueActions():
                available = self.actions_available
                yield QueueSendNow("Send now", disabled=not available)
                yield QueueClear("Clear queued inputs", disabled=not available)
                yield DismissButton("Close")

    def show_queue_error(self, text: str) -> None:
        self.query_one(QueueError).update(text)

    def close_inspection(self) -> None:
        self.dismiss()
