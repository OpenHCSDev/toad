"""Show queued messages, their delivery status and available actions."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from acp.exceptions import RequestError
from agent_comms.acp_extension import QueueScope
from agent_comms.errors import RelationViolationError, RouteChangedError, UnregisteredThreadError
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.css.native import NativeDeclaration, Variable
from textual.css.styles import Styles
from ui_theme.scheme import ErrorColour
from textual.widgets import Static

from toad.widgets.acting_button import ActingButton, DismissButton
from toad.acp.queue_attachment import QueueActionRefused
from toad.conversation_submission import ConversationSubmissions
from toad.line_blocks import SpanColumns
from toad.native_style import AutoHeight
from toad.screens.modal import CenteredScreen, ShadedScreen, SurfacePanel
from toad.screens.source_modal import SourceModal
from toad.submission_queue import QueueEvidence

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


class QueueInspection(ShadedScreen, CenteredScreen, SourceModal):
    """Shows the selected conversation's queue and delivery status."""

    def __init__(self, submissions: ConversationSubmissions) -> None:
        super().__init__()
        self.submissions = submissions
        self.source = submissions.view.queue_source
        self.evidence = submissions.queue_evidence
        self.scope = self.source.queue_scope(self.evidence)

    @property
    def source_view(self):
        return self.submissions.view

    def compose(self) -> ComposeResult:
        with QueuePanel():
            yield Static("Queue and delivery")
            with VerticalScroll():
                details = ToolContent()
                details.update((SpanColumns(self.source.queue_details(self.evidence)),))
                yield details
            yield Static("Editing, deleting and reordering individual queued messages isn't available here.")
            yield QueueError("")
            with QueueActions():
                available = self.source.queue_actions_available(self.evidence)
                yield QueueSendNow("Send now", disabled=not available)
                yield QueueClear("Clear queued inputs", disabled=not available)
                yield DismissButton("Close")

    async def apply_action(self, action: Callable[[QueueEvidence, QueueScope], Awaitable[None]]) -> None:
        try:
            await action(self.evidence, self.scope)
        except (QueueActionRefused, RequestError, RelationViolationError,
                RouteChangedError, UnregisteredThreadError) as error:
            self.query_one(QueueError).update(str(error))
            return
        self.submissions.publish_pending()
        self.dismiss()

    async def send_now(self) -> None:
        await self.apply_action(self.source.queue_send_now)

    async def clear_queue(self) -> None:
        await self.apply_action(self.source.queue_clear)
