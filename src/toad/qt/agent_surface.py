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
from weakref import ref

from agent_comms.transcript.transcript_events import NoticeTranscript
from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.client.subscribers import CallbackSubscription
from toad.core.events import CoreEvent
from toad.permission_presentation import DiffPermissionPresentation, InlinePermissionPresentation
from toad.qt.live_turn import QtLiveBlock
from toad.tool_output import ToolOutput
from toad.surface_binding import SurfaceBinding

if TYPE_CHECKING:
    from toad.core.events import CoreEventStream
    from toad.qt.conversation import QtConversation
    from toad.qt.history import QtHistoryWindow


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
        for handler in tuple(receiver.handlers_for(message.event)):
            arguments = (message.event, message) if _accepts_publication(handler) else (message.event,)
            result = handler(*arguments)
            if inspect.isawaitable(result):
                await result


class QtToolBlock(QtLiveBlock):
    """One tool call's row: its title and status, then its text output, redrawn in place as
    the agent updates the call."""

    event_kind = NoticeTranscript

    def __init__(self, window: QtHistoryWindow, tool_call_id: str) -> None:
        super().__init__(window, "")
        self.tool_call_id = tool_call_id

    def show(self, call) -> None:
        parts = (part.row_markdown for part in ToolOutput.capture_parts(call))
        self.text = "\n\n".join((f"🔧 **{call.title}** · {call.status or 'pending'}",
                                 *(part for part in parts if part)))
        self.finished = call.status in ("completed", "failed")
        self.revision += 1
        self.window.live_changed()


class QtTerminalBlock(QtLiveBlock):
    """A terminal the agent runs: its command, then its output, redrawn as it arrives. The
    shared `TerminalExecution` attaches it as its view, as it attaches Textual's terminal."""

    event_kind = NoticeTranscript

    def __init__(self, window: QtHistoryWindow, execution) -> None:
        super().__init__(window, "")
        self.execution = execution

    @property
    def is_attached(self) -> bool:
        return self in self.window.live_blocks

    def set_state(self, state) -> None:
        """The output is read from the execution; no terminal model is kept here."""

    def set_write_to_stdin(self, write) -> None:
        """A row takes no keyboard input."""

    def present_execution(self, scrollback, alternate) -> None:
        output, _truncated = self.execution.get_output()
        self.text = f"$ {self.execution.command}\n```\n{output.rstrip()}\n```"
        self.revision += 1
        self.window.live_changed()


class QtSurfaceBinding(SurfaceBinding, MroDispatch):
    """The surface a Qt conversation lends its bound agent."""

    def __init__(self, target: QtConversation, events: CoreEventStream) -> None:
        self._target = ref(target)
        self.subscription = target.subscribe_agent(events)
        self.tools: dict[str, QtToolBlock] = {}
        self.terminals: dict[str, QtTerminalBlock] = {}

    @property
    def target(self):
        return self._target()

    def owns_publication(self, message, target) -> bool:
        return (self.owns(target)
                and target.agent_binding.matches_agent(message.publisher)
                and message.publisher.controller.surface is self
                and message.publisher.tools.presentation(message.event) is not None)

    def sync_queue(self) -> None:
        if (target := self.target) is not None:
            target.submissions.publish_pending()

    async def present_tool(self, message, target) -> None:
        if not self.owns_publication(message, target):
            return
        status = message.event.tool_call
        status.activity(target.turns, target.output, status.title)
        call = status.call
        block = self.tools.get(call.tool_call_id)
        if block is None:
            target.output.boundary()
            block = self.tools[call.tool_call_id] = QtToolBlock(target.messages, call.tool_call_id)
            target.messages.show_live(block)
        block.show(call)

    async def present_permission(self, request, view) -> None:
        await self.dispatch(request.presentation, view, request)

    @handles(InlinePermissionPresentation)
    async def ask_inline(self, presentation, view, request) -> None:
        self.ask(view, request, presentation.title)

    @handles(DiffPermissionPresentation)
    async def ask_file_write(self, presentation, view, request) -> None:
        """As Textual's file-write review, it also notifies the desktop."""
        title = f"{view.agent_title} would like to write files"
        self.ask(view, request, title)
        view.app.input_attention.notify(title, title="Permissions request", sound="question")

    def ask(self, view, request, title: str) -> None:
        """Every permission asks through the view's shared question (`QtQuestion`, a
        `ChoiceQuestion`), and its answer goes back to the request."""
        ask = view.ask(request.options, title, None, partial(request.answer, self))

        def retire() -> None:
            view.retract(ask)

        request.watch(self, retire)

    def permission_changed(self, view) -> None:
        """Qt binds no permission keys beyond the question's own."""

    def publish_terminal(self, controller, terminal_id, execution) -> bool:
        target = self.target
        if target is None or not controller.owner.owns_terminal(self, controller, terminal_id, execution):
            return False
        block = self.terminals.get(terminal_id)
        if block is None or block.execution is not execution:
            if block is not None:
                target.messages.drop_live(block)
            target.output.boundary()
            block = self.terminals[terminal_id] = QtTerminalBlock(target.messages, execution)
            target.messages.show_live(block)
        execution.attach(block)
        return True

    def prepare_terminal(self, state) -> None:
        """A row has no character grid: the terminal keeps its configured size."""

    def post(self, message) -> bool:
        """Qt delivers the agent's stream through `subscribe_agent`, not posted messages."""
        return False

    def close(self) -> None:
        if (target := self.target) is not None:
            target.retire_core(self.subscription)
        else:
            self.subscription.close()


def subscribe_agent(observer, events: CoreEventStream):
    """The view's subscription to its agent's whole stream, delivered on Qt's loop."""
    subscription = events.subscribe(CoreEvent, observer.post_core_callback, factory=partial(
        AgentEventSubscription, callback=observer.consume_handlers))
    observer._core_subscriptions.add(subscription)
    return subscription
