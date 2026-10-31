"""Inspect the captured queue source through the actual conversation view."""
from __future__ import annotations

from typing import TYPE_CHECKING

from acp.exceptions import RequestError
from textual import on
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.widgets import Button, Static

from toad.acp.queue_attachment import QueueActionRefused
from toad.line_blocks import SpanColumns
from toad.screens.source_modal import SourceModal
from toad.widgets.tool_content import ToolContent

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent_comms.acp_extension import QueueScope
    from toad.agent_presentation import AgentPresentation
    from toad.conversation_submission import ConversationSubmissions


class QueueInspection(SourceModal):
    """One screen captures the source, presentation and scope it actually displays."""

    DEFAULT_CSS = """
    QueueInspection { align: center middle; background: $background 40%; }
    QueueInspection > Vertical { width: 85%; max-width: 110; height: 75%; padding: 1 2; background: $surface; }
    QueueInspection VerticalScroll { height: 1fr; }
    QueueInspection HorizontalGroup { height: auto; }
    QueueInspection #queue-error { height: auto; color: $error; }
    """

    def __init__(self, submissions: ConversationSubmissions) -> None:
        super().__init__()
        self.submissions = submissions
        self.source = submissions.view.queue_source
        self.evidence = submissions.queue_evidence
        self.scope = self.source.queue_scope(self.evidence.presentation)

    @property
    def source_view(self):
        return self.submissions.view

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Queue and delivery")
            with VerticalScroll():
                details = ToolContent()
                details.update((SpanColumns(self.source.queue_details(self.evidence)),))
                yield details
            yield Static("Individual edit/delete/reorder requires ID-targeted, revision-checked backend support.")
            yield Static("", id="queue-error")
            with HorizontalGroup():
                available = self.source.queue_actions_available(self.evidence.presentation)
                yield Button("Send now", id="queue-send-now", disabled=not available)
                yield Button("Clear queued inputs", id="queue-clear", disabled=not available)
                yield Button("Close", id="queue-close")

    async def apply_action(self, action: Callable[[AgentPresentation, QueueScope], Awaitable[None]]) -> None:
        try:
            await action(self.evidence.presentation, self.scope)
        except (QueueActionRefused, RequestError) as error:
            self.query_one("#queue-error", Static).update(str(error))
            return
        self.submissions.publish_pending()
        self.dismiss()

    @on(Button.Pressed, "#queue-send-now")
    async def send_now(self) -> None:
        await self.apply_action(self.source.queue_send_now)

    @on(Button.Pressed, "#queue-clear")
    async def clear_queue(self) -> None:
        await self.apply_action(self.source.queue_clear)

    @on(Button.Pressed, "#queue-close")
    def close_queue(self) -> None:
        self.dismiss()
