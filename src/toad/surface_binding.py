"""Native surface behavior borrowed by agent and shell operational owners."""

from abc import abstractmethod
from agent_comms.declared_family import DeclaredFamily


class SurfaceBinding(DeclaredFamily, affix="SurfaceBinding"):
    target = None

    def owns(self, target):
        return self.target is target and target is not None

    def prepare(self, controller) -> None:
        """No frontend means no additional application resources to acquire."""

    def prepare_terminal(self, state) -> None:
        """A detached terminal keeps its original model's configured geometry."""

    def prepare_shell(self, source) -> None:
        """A detached shell retains its original directory and terminal size."""

    async def present_shell(self, output) -> None:
        """An absent frontend never acquires shell projection resources."""

    def shell_failed(self, error) -> None:
        """An absent frontend has no native notification to acquire."""

    async def present_permission(self, request, view) -> None:
        """An absent frontend never acquires a permission projection."""

    def permission_changed(self, view) -> None:
        """An absent frontend has no permission bindings to invalidate."""

    async def present_failure(self, failure, view) -> None:
        """An absent frontend keeps the original failure without native work."""

    def schedule_terminal_presentation(self, controller):
        controller.start_terminal_presentation(self.target)

    def publish_terminal(self, controller, terminal_id, execution):
        """An absent frontend does not acquire native projection work."""
        return False

    @abstractmethod
    def post(self, message) -> bool: ...

    def close(self) -> None:
        """An absent frontend has no subscription to release."""


class DetachedSurfaceBinding(SurfaceBinding):
    def post(self, message):
        return False


