"""Textual attachment borrows original agent services and projection resources."""

from weakref import ref

from toad.acp.agent_controller import SurfaceBinding, ApplicationValidationOwner

class AttachedSurfaceBinding(SurfaceBinding):
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
