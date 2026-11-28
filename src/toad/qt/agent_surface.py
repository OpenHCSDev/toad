"""How a Qt conversation receives its bound agent: Textual's `AttachedSurfaceBinding`, on Qt.

The agent publishes its turn on its event stream and asks its surface to present tool calls,
permission requests and terminals. Textual receives the stream through its message pump and
mounts widgets; Qt receives it on its own loop (`QtCoreObserver`) and draws each piece as a
live row in the history window, beside the turn's response and thought rows (`live_turn`).
The shared handlers (`AgentTurnEvents`) decide what each event does; this module only draws.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from acp import schema
from agent_comms.nominal.field_codec import FieldCodec, ToolCallId
from agent_comms.transcript.transcript_events import ToolStartTranscript
from metaclass_registry.mro_dispatch import handles

from toad.acp.status import ToolCallStatus
from toad.client.fragments import GrowsInPlace, Shown
from toad.client.subscribers import CallbackSubscription
from toad.commit_claims import CAPTURED_CLAIM, CapturedClaim, SnapshotPresentation
from toad.core.link_context_changed import CoreEvent, CoreEventStream
from toad.permission_presentation import (
    DialogPermissionPresentation,
    DiffPermissionPresentation,
    InlinePermissionPresentation,
)
from toad.qt.history import QtHistoryWindow
from toad.qt.transcript_fragments import QtToolTranscriptFragment
from toad.qt.live_turn import QtLiveBlock
from toad.tool_output import TextToolOutputPart, ToolOutput
from toad.surface_binding import NonPostingSurfaceBinding, ViewSurfaceBinding

if TYPE_CHECKING:
    from toad.qt.conversation import QtConversation


def _accepts_publication(handler) -> bool:
    """Whether a handler declares the publication beside the event, as Textual's `invoke`
    decides from the handler's own parameters."""
    parameters = [
        parameter for parameter in inspect.signature(handler).parameters.values()
        if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(parameters) >= 2


@dataclass(eq=False)
class AgentEventSubscription(CallbackSubscription):
    """The agent's stream, delivered to the view's own declared handlers: each receives the
    event, and the publication when it declares it."""

    async def consume(self, receiver, message) -> None:
        if not message.subscription.active or not receiver.accepts(message):
            return
        for handler in tuple(receiver.handlers_for(message.event)):
            arguments = (message.event, message) if _accepts_publication(handler) else (message.event,)
            result = handler(*arguments)
            if inspect.isawaitable(result):
                await result


@dataclass(kw_only=True)
class QtLiveToolFragment(GrowsInPlace, QtToolTranscriptFragment):
    """A live tool call's row, drawn as a saved one is (`AgentActivityPresentation.tool`: the
    title and status, details behind the disclosure); its revision keys the row cache."""


class QtLiveToolRow(QtLiveBlock):
    """A live row that draws one ACP tool call as history draws a recorded one."""

    shown = Shown()

    def __init__(self, window: QtHistoryWindow) -> None:
        super().__init__(window, "")

    @property
    def loading(self) -> bool:
        return False

    def call(self) -> schema.ToolCall: ...

    def output_parts(self, call: schema.ToolCall):
        return ToolOutput.capture_parts(call)

    def fragment(self) -> QtLiveToolFragment:
        call = self.call()
        event = ToolStartTranscript(tool_call_id=FieldCodec.decode(ToolCallId, call.tool_call_id),
                                    tool_name=call.title, raw_input={},
                                    position=self.position, timestamp=self.timestamp)
        return QtLiveToolFragment(events=(event,), tool_call=ToolCallStatus.from_acp(call),
                                  output_parts=self.output_parts(call), shown=self.shown,
                                  live_revision=self.revision)

    def redraw(self) -> None:
        self.revision += 1
        self.window.live_changed()


class QtToolBlock(SnapshotPresentation, QtLiveToolRow):
    """One tool call's row, redrawn in place as the agent updates the call."""

    def __init__(
        self,
        window: QtHistoryWindow,
        call: schema.ToolCall,
        *,
        source_claim: CapturedClaim = CAPTURED_CLAIM,
    ) -> None:
        super().__init__(window)
        self.current = call
        self.source_claim = source_claim
        self.finished = call.status in ("completed", "failed")

    def call(self) -> schema.ToolCall:
        return self.current

    def show(self, call: schema.ToolCall) -> None:
        self.current = call
        self.finished = call.status in ("completed", "failed")
        self.redraw()


class QtTerminalBlock(QtLiveToolRow):
    """A terminal the agent runs: its command as the title and its output open beneath, as
    Textual's `TerminalTool` shows it. The shared `TerminalExecution` attaches it as its view,
    as it attaches Textual's terminal."""

    shown = Shown(details_open=True)

    def __init__(self, window: QtHistoryWindow, terminal_id: str, execution) -> None:
        super().__init__(window)
        self.terminal_id = terminal_id
        self.execution = execution

    def call(self) -> schema.ToolCall:
        return schema.ToolCall(tool_call_id=self.terminal_id, title=f"$ {self.execution.command}",
                               kind="execute", status="completed" if self.finished else "in_progress")

    def output_parts(self, call: schema.ToolCall):
        output, _truncated = self.execution.get_output()
        return (TextToolOutputPart.from_text(output.rstrip(), None),) if output.strip() else ()

    def set_state(self, state) -> None:
        """The output is read from the execution; no terminal model is kept here."""

    def set_write_to_stdin(self, write) -> None:
        """A row takes no keyboard input."""

    def present_execution(self, scrollback, alternate) -> None:
        self.finished = self.execution.operation.outcome().finished
        self.redraw()


class QtSurfaceBinding(NonPostingSurfaceBinding, ViewSurfaceBinding):
    """The surface a Qt conversation lends its bound agent."""

    def __init__(self, target: QtConversation, events: CoreEventStream) -> None:
        self.lend(target, target.subscribe_agent(events))
        self.tools: dict[str, QtToolBlock] = {}
        self.terminals: dict[str, QtTerminalBlock] = {}

    async def show_tool_call(self, message, target, status) -> None:
        call = status.call
        block = self.tools.get(call.tool_call_id)
        if block is None or not block.is_attached:
            target.output.boundary()
            claim = message.publisher.tools.presentation(message.event).source_claim
            block = self.tools[call.tool_call_id] = QtToolBlock(target.messages, call, source_claim=claim)
            target.messages.show_live(block)
        else:
            block.show(call)

    @handles(InlinePermissionPresentation)
    async def ask_inline(self, presentation, view, request) -> None:
        self.ask(view, request, presentation.title)

    @handles(DiffPermissionPresentation)
    async def ask_file_write(self, presentation, view, request) -> None:
        """As Textual's file-write review, it also notifies the desktop."""
        title = f"{view.agent_title} would like to write files"
        self.ask(view, request, title)
        view.app.input_attention.notify(title, title="Permissions request", sound="question")

    @handles(DialogPermissionPresentation)
    async def ask_dialog(self, presentation: DialogPermissionPresentation, view, request) -> None:
        view.open_dialog(presentation.spec, partial(request.resolve, self))
        view.app.input_attention.notify(
            presentation.spec.message or presentation.spec.title,
            title=presentation.spec.title or "Input requested",
            sound="question",
        )
        request.watch(self, partial(view.retract_dialog, presentation.spec))

    def ask(self, view, request, title: str) -> None:
        """Every permission asks through the view's shared question (`QtQuestion`, a
        `ChoiceQuestion`), and its answer goes back to the request."""
        ask = view.ask(request.options, title, None, partial(request.answer, self))

        def retire() -> None:
            view.retract(ask)

        request.watch(self, retire)

    def publish_terminal(self, controller, terminal_id, execution) -> bool:
        target = self.target
        if target is None or not controller.owner.owns_terminal(self, controller, terminal_id, execution):
            return False
        block = self.terminals.get(terminal_id)
        if block is None or block.execution is not execution:
            if block is not None:
                target.messages.drop_live(block)
            target.output.boundary()
            block = self.terminals[terminal_id] = QtTerminalBlock(target.messages, terminal_id, execution)
            target.messages.show_live(block)
        execution.attach(block)
        return True


def subscribe_agent(observer, events: CoreEventStream):
    """The view's subscription to its agent's whole stream, delivered on Qt's loop."""
    subscription = events.subscribe(CoreEvent, observer.post_core_callback, factory=partial(
        AgentEventSubscription, callback=observer.consume_handlers))
    observer._core_subscriptions.add(subscription)
    return subscription
