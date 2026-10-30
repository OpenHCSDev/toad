"""Inspect the captured queue source through the actual conversation view."""

from collections.abc import Awaitable, Callable

from acp.exceptions import RequestError
from agent_comms.acp_extension import QueueScope
from textual import on
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.widgets import Button, Static

from toad.acp.queue_attachment import QueueActionRefused
from toad.agent_presentation import AgentPresentation
from toad.line_blocks import SpanColumns
from toad.screens.modal import DismissibleScreen
from toad.submission_queue import QueueEvidence, QueueSource
from toad.widgets.tool_content import ToolContent


class QueueInspection(DismissibleScreen[None]):
    """One screen captures the source, presentation and scope it actually displays."""

    DEFAULT_CSS = """
    QueueInspection { align: center middle; background: $background 40%; }
    QueueInspection > Vertical { width: 85%; max-width: 110; height: 75%; padding: 1 2; background: $surface; }
    QueueInspection VerticalScroll { height: 1fr; }
    QueueInspection HorizontalGroup { height: auto; }
    QueueInspection #queue-error { height: auto; color: $error; }
    """

    def __init__(self, source: QueueSource, evidence: QueueEvidence, changed: Callable[[], None]) -> None:
        super().__init__()
        self.source, self.evidence = source, evidence
        self.scope = source.queue_scope(evidence.presentation)
        self.changed = changed

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
        self.changed()
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
