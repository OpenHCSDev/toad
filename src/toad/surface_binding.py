"""Native surface behavior borrowed by agent and shell operational owners."""

from abc import abstractmethod
from weakref import ref

from agent_comms.nominal.declared_family import DeclaredFamily
from metaclass_registry.mro_dispatch import MroDispatch
from toad.core import events as core_events


class SurfaceBinding(DeclaredFamily, affix="SurfaceBinding"):
    target = None

    def owns(self, target):
        return self.target is target and target is not None

    def prepare(self, controller) -> None:
        """No frontend means no additional application resources to acquire."""

    def sync_queue(self) -> None:
        """A detached source has no queue summary to refresh."""

    def prepare_terminal(self, state) -> None:
        """A detached terminal keeps its original model's configured geometry."""

    def prepare_shell(self, source) -> None:
        """A detached shell retains its original directory and terminal size."""

    async def present_tool(self, message, target) -> None:
        """A detached frontend acquires neither tool nor separate message body."""

    async def present_shell(self, output) -> None:
        """An absent frontend never acquires shell projection resources."""

    def shell_failed(self, error) -> None:
        """An absent frontend has no native notification to acquire."""

    async def present_permission(self, request, view) -> None:
        """An absent frontend never acquires a permission projection."""

    def permission_changed(self, view) -> None:
        """An absent frontend has no permission bindings to invalidate."""

    def schedule_terminal_presentation(self, controller):
        controller.start_terminal_presentation(self.target)

    def publish_terminal(self, controller, terminal_id, execution):
        """An absent frontend does not acquire native projection work."""
        return False

    @abstractmethod
    def post(self, message) -> bool: ...

    def close(self) -> None:
        """An absent frontend has no subscription to release."""

    async def publish_transcript_snapshot(self, session, update, owner) -> None:
        if self.target is None or not session.accepts_snapshot(update.identity, owner.agent):
            return
        snapshot = await owner.transcripts.publication(update)
        if owner.session is not session:
            return
        if owner.surface is not self:
            return
        if not session.accepts_snapshot(snapshot.identity, owner.agent):
            return
        owner.agent.events.publish(core_events.CommsUpdated(snapshot, session.session_id))


class NonPostingSurfaceBinding(SurfaceBinding, declared_name=None):
    """Surface bindings that deliver without posting Textual messages."""

    def post(self, message) -> bool:
        return False


class ViewSurfaceBinding(SurfaceBinding, MroDispatch):
    """The surface a frontend's view lends its bound agent: it holds the view weakly, so a
    closed view is no target, and the view's subscription to the agent's stream."""

    def lend(self, target, subscription) -> None:
        self._target = ref(target)
        self.subscription = subscription

    @property
    def target(self):
        return self._target()

    def owns_publication(self, message, target) -> bool:
        return (
            self.subscription.accepts(message.subscription)
            and self.owns(target)
            and target.agent_binding.matches_agent(message.publisher)
            and message.publisher.controller.surface is self
            and target.is_attached
            and message.publisher.tools.presentation(message.event) is not None
        )

    async def present_tool(self, message, target) -> None:
        if not self.owns_publication(message, target):
            return
        status = message.event.tool_call
        status.activity(target.turns, target.output, status.title)
        await self.show_tool_call(message, target, status)

    @abstractmethod
    async def show_tool_call(self, message, target, status) -> None:
        """Render a tool call update once ownership and turn activity have been checked."""

    async def present_permission(self, request, view) -> None:
        await self.dispatch(request.presentation, view, request)

    def sync_queue(self) -> None:
        if (target := self.target) is not None:
            target.submissions.publish_pending()

    def close(self) -> None:
        if (target := self.target) is not None:
            target.retire_core(self.subscription)
        else:
            self.subscription.close()


class DetachedSurfaceBinding(NonPostingSurfaceBinding, SurfaceBinding):
    pass


