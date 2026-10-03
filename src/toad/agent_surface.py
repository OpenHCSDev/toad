"""Textual attachment borrows original agent services and projection resources."""

from weakref import ref
from functools import partial

from agent_comms.mro_dispatch import MroDispatch, handles
from toad.surface_binding import SurfaceBinding
from toad.acp.agent_controller import ApplicationValidationOwner
from toad.permission_presentation import DiffPermissionPresentation, InlinePermissionPresentation
from toad.core.events import HelpAgentFail, LogAgentFail
from toad.shell_output import ShellCommandOutput, ShellTerminalOutput

class AttachedSurfaceBinding(SurfaceBinding, MroDispatch):
    def __init__(self, target, events):
        self._target = ref(target)
        self.subscription = target.subscribe_core(events)

    def prepare(self, controller) -> None:
        app = self.target.app
        controller.transcripts = controller.transcripts.with_runtime(
            app.preparation, app.coordination_access)
        controller.validation = ApplicationValidationOwner(app.render_processes)

    def prepare_terminal(self, state) -> None:
        target = self.target
        if target is not None:
            state.update_size(*target.get_terminal_dimensions())

    def prepare_shell(self, source) -> None:
        if (target := self.target) is not None:
            target.working_directory = source.working_directory
            source.update_size(*target.get_terminal_dimensions())

    async def present_shell(self, output) -> None:
        if (target := self.target) is not None:
            await self.dispatch(output, target)

    @handles(ShellCommandOutput)
    async def show_shell_command(self, output, target):
        from toad.widgets.shell_result import ShellResult

        if not any(result.source is output for result in target.query(ShellResult)):
            await target.post(ShellResult(output))

    @handles(ShellTerminalOutput)
    async def show_shell_terminal(self, output, target):
        if output.terminal is None:
            from toad.widgets.shell_terminal import ShellTerminal

            terminal = next((terminal for terminal in target.query(ShellTerminal)
                             if terminal.state is output.state), None)
            if terminal is None:
                terminal = await target.new_terminal()
            output.attach(terminal)

    def shell_failed(self, error) -> None:
        if (target := self.target) is not None:
            target.app.notify(f"Unable to start shell: {error}\n\nCheck your settings.",
                              title="Shell", severity="error")

    async def present_failure(self, failure, view) -> None:
        if self.owns(view):
            await self.dispatch(failure, view)

    @handles(HelpAgentFail)
    async def show_failure_help(self, failure, view):
        from toad.widgets.markdown_note import MarkdownNote

        await view.post(MarkdownNote(failure.help_text))

    @handles(LogAgentFail)
    async def show_failure_log(self, failure, view):
        from urllib.parse import quote
        from toad.widgets.agent_response import AgentResponse
        from toad.widgets.message_filter import OtherCategory

        link = AgentResponse(f"[Open ACP log]({quote(str(failure.log_path))})",
                             show_divider=False, category=OtherCategory)
        link.add_class("-error-log-link")
        await view.post(link)

    async def present_permission(self, request, view) -> None:
        await self.dispatch(request.presentation, view, request)

    def permission_changed(self, view) -> None:
        view.refresh_bindings()

    @handles(DiffPermissionPresentation)
    async def show_file_permission(self, presentation, view, request):
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
    async def show_inline_permission(self, presentation, view, request):
        from toad.widgets.acp_content import ACPToolCallContent
        from toad.tool_output import decode_content

        parts = tuple(preview for item in presentation.parts
                      if (preview := decode_content(item).permission_preview()) is not None)

        def answer(answer):
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

    def schedule_terminal_presentation(self, controller):
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

    def post(self, message):
        target = self.target
        # The original MessagePump owns admission while closing/closed.
        return target.post_message(message) if target is not None else False

    def publish_terminal(self, controller, terminal_id, execution):
        from toad.widgets.terminal_tool import TerminalTool
        return self.post(TerminalTool.Projection(self, controller, terminal_id, execution))

    def owns_terminal(self, projection, target):
        """Same original surface, controller lifetime and acquired address."""
        if not self.owns(target):
            return False
        return projection.controller.owner.owns_terminal_projection(self, projection)

    async def present_terminal(self, projection, target):
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
