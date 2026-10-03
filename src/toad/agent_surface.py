"""Textual attachment borrows original agent services and projection resources."""

from weakref import ref
from functools import partial

from agent_comms.mro_dispatch import MroDispatch, handles
from toad.acp.agent_controller import SurfaceBinding, ApplicationValidationOwner
from toad.permission_presentation import DiffPermissionPresentation, InlinePermissionPresentation

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

    async def present_permission(self, request, view) -> None:
        if (not request.pending or request.projected_on(view) or not self.owns(view)
                or request.controller.agent.controller.surface is not self):
            return
        presentation = request.presentation
        handlers = tuple(self.handlers_for(presentation))
        if not handlers:
            raise TypeError(f"No native permission view for {type(presentation).__name__}")
        view.refresh_bindings()
        for handler in handlers:
            await handler(presentation, view, request)

    @handles(DiffPermissionPresentation)
    async def show_file_permission(self, presentation, view, request):
        from toad.screens.permissions import PermissionReview

        screen = PermissionReview(request, view, presentation.diffs, self)
        app = view.app
        try:
            app.terminal_attention.require(screen)
            app.terminal_attention.notify(f"{view.agent_title} would like to write files",
                                          title="Permissions request", sound="question")
            request.watch(view, screen.retire)
            result = await app.push_screen_wait(screen, mode=view.screen.id)
            request.answer(self, result)
        finally:
            app.terminal_attention.release(screen)
            if request.controller.agent.controller.surface is self:
                view.refresh_bindings()

    @handles(InlinePermissionPresentation)
    async def show_inline_permission(self, presentation, view, request):
        from toad.widgets.acp_content import ACPToolCallContent
        from toad.tool_output import decode_content

        parts = tuple(preview for item in presentation.parts
                      if (preview := decode_content(item).permission_preview()) is not None)

        def answer(answer):
            if request.controller.agent.controller.surface is not self:
                return
            request.answer(self, answer)
            if not view.prompt.ask_queue:
                view.refresh_bindings()

        ask = view.ask(request.options, presentation.title,
                       partial(ACPToolCallContent, parts) if parts else None,
                       answer)

        def retire():
            if view.is_attached:
                view.prompt.remove_ask(ask)
                if view.prompt._ask is None:
                    view.refresh_bindings()

        request.watch(view, retire)

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
                return  # Reuse the original bounded rendering resource.
            await existing.remove()  # A replaced ACP controller may reuse its address.
            if not self.owns_terminal(projection, target):
                return
        terminal = TerminalTool(projection.execution, id=projection.terminal_id)
        await target.post(terminal)
        if not self.owns_terminal(projection, target):
            await terminal.remove()
