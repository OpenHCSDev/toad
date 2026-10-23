"""Textual attachment borrows original agent services and projection resources."""

from weakref import ref
from contextlib import AsyncExitStack
from functools import partial
from typing import TYPE_CHECKING

from agent_comms.mro_dispatch import MroDispatch, handles
from toad.surface_binding import SurfaceBinding
from toad.acp.agent_controller import ProcessTaskRunner
from toad.permission_presentation import DiffPermissionPresentation, InlinePermissionPresentation
from toad.shell_output import ShellCommandOutput, ShellTerminalOutput

if TYPE_CHECKING:
    from textual.message import Message
    from textual.widget import Widget

    from toad.acp.agent_controller import AgentController
    from toad.acp.permission_controller import PermissionRequest
    from toad.acp.terminal_controller import TerminalController
    from toad.acp.terminal_owner import OperationalTerminalOwner
    from toad.ansi import TerminalState
    from toad.answer import Answer
    from toad.core.events import CoreEventStream
    from toad.core_event_carrier import CoreEventMessage
    from toad.shell_output import ShellOutput
    from toad.terminal_execution import TerminalExecution
    from toad.widgets.conversation import Conversation
    from toad.widgets.terminal_tool import TerminalTool


class AttachedSurfaceBinding(SurfaceBinding, MroDispatch):
    def __init__(self, target: Conversation, events: CoreEventStream):
        self._target = ref(target)
        self.subscription = target.subscribe_core(events)

    def prepare(self, controller: AgentController) -> None:
        app = self.target.app
        controller.task_runner = ProcessTaskRunner(app.render_processes)

    def owns_publication(self, message: CoreEventMessage, target: Conversation):
        if not self.subscription.accepts(message.subscription):
            return False
        if not self.owns(target) or not target.agent_binding.matches_agent(message.publisher):
            return False
        if message.publisher.controller.surface is not self:
            return False
        return target.is_attached and message.publisher.tools.presentation(message.event) is not None

    async def _post_native(
        self, message: CoreEventMessage, target: Conversation, widget: Widget, retirement: AsyncExitStack,
    ):
        if not self.owns_publication(message, target):
            return False
        retirement.push_async_callback(target.transcript.retire_presentations,
                                       target.contents, target.output, [widget])
        await target.post(widget, new_block=True)
        return self.owns_publication(message, target) and widget.is_attached

    async def present_tool(self, message: CoreEventMessage, target: Conversation):
        from toad.tool_output import ToolOutput
        from toad.widgets.outgoing_message import OutgoingMessage
        from toad.widgets.tool_call import ToolCall

        if not self.owns_publication(message, target):
            return
        event = message.event
        request = message.publisher.tools.presentation(event).request
        status = event.tool_call
        status.activity(target.turns, target.output, status.title)
        parts = await target.app.preparation.run_thread(
            ToolOutput.capture_projection, status, event.scope,
        )
        if not self.owns_publication(message, target):
            return
        async with AsyncExitStack() as retirement:
            for part in parts:
                for sent in part.standalone_messages:
                    body = OutgoingMessage(sent.message, row=sent.row, binding=self, request=request)
                    if not await self._post_native(message, target, body, retirement):
                        return
            if not self.owns_publication(message, target):
                return
            tool = target.contents.query_one_optional(f"#{event.tool_id}", ToolCall)
            if tool is not None and (tool.binding is not self or tool.request is not request):
                await target.transcript.retire_presentations(target.contents, target.output, [tool])
                tool = None
            if not self.owns_publication(message, target):
                return
            if tool is None:
                tool = ToolCall(status, id=event.tool_id, output_parts=parts, binding=self, request=request)
                if not await self._post_native(message, target, tool, retirement):
                    return
            else:
                tool.update_tool_call(status, output_parts=parts)
            if self.owns_publication(message, target):
                retirement.pop_all()

    def sync_queue(self) -> None:
        if (target := self.target) is not None:
            target.submissions.publish_pending()

    def prepare_terminal(self, state: TerminalState) -> None:
        target = self.target
        if target is not None:
            state.update_size(*target.get_terminal_dimensions())

    def prepare_shell(self, source) -> None:
        if (target := self.target) is not None:
            target.working_directory = source.working_directory
            source.update_size(*target.get_terminal_dimensions())

    async def present_shell(self, output: ShellOutput) -> None:
        if (target := self.target) is not None:
            await self.dispatch(output, target)

    @handles(ShellCommandOutput)
    async def show_shell_command(self, output: ShellCommandOutput, target: Conversation):
        from toad.widgets.shell_result import ShellResult

        if not any(isinstance(child, ShellResult) and child.source is output
                   for child in target.contents.children):
            await target.post(ShellResult(output))

    @handles(ShellTerminalOutput)
    async def show_shell_terminal(self, output: ShellTerminalOutput, target: Conversation):
        if output.terminal is None:
            from toad.widgets.shell_terminal import ShellTerminal

            terminal = next((terminal for terminal in target.query(ShellTerminal)
                             if terminal.state is output.state), None)
            if terminal is None:
                terminal = await target.new_terminal()
            output.attach(terminal)

    def shell_failed(self, error: Exception) -> None:
        if (target := self.target) is not None:
            target.app.show_error(error, "Unable to start shell; check your settings")

    async def present_permission(self, request: PermissionRequest, view: Conversation) -> None:
        await self.dispatch(request.presentation, view, request)

    def permission_changed(self, view: Conversation) -> None:
        view.refresh_bindings()

    @handles(DiffPermissionPresentation)
    async def show_file_permission(
        self, presentation: DiffPermissionPresentation, view: Conversation, request: PermissionRequest,
    ):
        from toad.screens.permissions import PermissionReview

        screen = PermissionReview(request, view, presentation.diffs, self)
        app = view.app
        if not request.watch(self, screen.retire):
            return
        try:
            app.terminal_attention.require(screen)
            app.terminal_attention.notify(f"{view.agent_title} would like to write files",
                                          title="Permissions request", sound="question")
            result = await app.push_screen_wait(screen, mode=view.screen.id)
            request.answer(self, result)
        finally:
            app.terminal_attention.release(screen)

    @handles(InlinePermissionPresentation)
    async def show_inline_permission(
        self, presentation: InlinePermissionPresentation, view: Conversation, request: PermissionRequest,
    ):
        from toad.widgets.acp_content import ACPToolCallContent
        from toad.tool_output import decode_content

        parts = tuple(preview for item in presentation.parts
                      if (preview := decode_content(item).permission_preview()) is not None)

        def answer(answer: Answer):
            request.answer(self, answer)

        ask = view.ask(request.options, presentation.title,
                       partial(ACPToolCallContent, parts) if parts else None,
                       answer)

        def retire():
            if view.is_attached:
                view.prompt.remove_ask(ask)
                if view.prompt._ask is None:
                    view.refresh_bindings()

        request.watch(self, retire)

    def schedule_terminal_presentation(self, controller: OperationalTerminalOwner):
        if (target := self.target) is not None:
            target.call_later(controller.start_terminal_presentation, target)

    def close(self) -> None:
        if (target := self.target) is not None:
            target.retire_core(self.subscription)
        else:
            self.subscription.close()

    @property
    def target(self):
        return self._target()

    def post(self, message: Message):
        target = self.target
        # MessagePump decides whether to accept messages while closing/closed.
        return target.post_message(message) if target is not None else False

    def publish_terminal(self, controller: TerminalController, terminal_id: str, execution: TerminalExecution):
        from toad.widgets.terminal_tool import TerminalTool
        return self.post(TerminalTool.Projection(self, controller, terminal_id, execution))

    def owns_terminal(self, projection: TerminalTool.Projection, target: Conversation):
        """Same original surface, controller lifetime and acquired address."""
        if not self.owns(target):
            return False
        return projection.controller.owner.owns_terminal_projection(self, projection)

    async def present_terminal(self, projection: TerminalTool.Projection, target: Conversation):
        if not self.owns_terminal(projection, target):
            return
        from toad.widgets.terminal_tool import TerminalTool

        if existing := target.query_one_optional(f"#{projection.terminal_id}", TerminalTool):
            if existing.execution is projection.execution:
                projection.execution.attach(existing)
                return  # Reuse the original bounded rendering resource.
            await existing.remove()  # A replaced ACP controller may reuse its address.
            if not self.owns_terminal(projection, target):
                return
        terminal = TerminalTool(projection.execution, id=projection.terminal_id)
        await target.post(terminal)
        if not self.owns_terminal(projection, target):
            await terminal.remove()
