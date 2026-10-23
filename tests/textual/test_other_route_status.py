"""A mounted status row explains another route without reading its stores."""

from agent_comms.ui_model.status import ThreadStatusModel
from textual.app import ComposeResult
from textual.containers import Vertical

from toad.status_thread import StatusThread
from toad.widgets.observed_thread_activity import (
    ObservedThreadActivity,
    ThreadStatusOwner,
)


class OtherRouteStatusSurface(ThreadStatusOwner, Vertical):
    def __init__(self, source: StatusThread):
        super().__init__()
        self.source = source
        self.thread_activity = ObservedThreadActivity()

    def compose(self) -> ComposeResult:
        yield self.thread_activity

    def on_mount(self) -> None:
        self.thread_activity.bind(self.source)

    def status_thread(self) -> StatusThread:
        return self.source


async def test_other_route_binds_its_status_without_starting_a_read(workspace):
    other_root = workspace.roots.attempt / "not-selected"
    async with workspace.app() as ui:
        app, _ = ui.textual
        source = StatusThread.for_root(other_root, "peer", app.coordination_access)
        surface = OtherRouteStatusSurface(source)
        await app.selected_session.mount(surface)
        source.refresh(surface)
        assert surface.thread_activity.row == ThreadStatusModel.other_route("peer")
        assert not any(
            surface in worker.node.walk_ancestors(with_self=True)
            for worker in app.workers
        )
        assert not other_root.exists()
