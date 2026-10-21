"""Deferred Core reads retain the actual mounted status display."""

import pytest
from agent_comms.bus_route_counts import RouteIndexRebuilding
from agent_comms.comms import Comms
from agent_comms.coordination_errors import CoordinationReadUnavailable
from agent_comms.ui_model.observation import ReadDeferred, ReadPreparing
from agent_comms.ui_model.status import ThreadStatusModel
from textual.app import ComposeResult
from textual.containers import Vertical

from toad.status_thread import ForeignStatusThread
from toad.widgets.observed_thread_activity import (
    ObservedThreadActivity,
    ThreadStatusOwner,
)


class ForeignStatusSurface(ThreadStatusOwner, Vertical):
    thread_activity: ObservedThreadActivity

    def __init__(self, source: ForeignStatusThread):
        super().__init__()
        self.source = source
        self.thread_activity = ObservedThreadActivity()

    def compose(self) -> ComposeResult:
        yield self.thread_activity

    def on_mount(self) -> None:
        self.thread_activity.bind(self.source)

    def status_thread(self) -> ForeignStatusThread:
        return self.source


@pytest.mark.parametrize(
    "read",
    [
        ReadDeferred(CoordinationReadUnavailable("busy snapshot")),
        ReadPreparing(RouteIndexRebuilding(1, 2)),
    ],
)
async def test_deferred_foreign_read_keeps_the_previous_status_row(workspace, read):
    async with workspace.app() as ui:
        app, _ = ui.textual
        source = ForeignStatusThread(workspace.project / "foreign", "peer")
        surface = ForeignStatusSurface(source)
        await app.selected_session.mount(surface)
        previous = ThreadStatusModel.pending("previous-status")
        surface.thread_activity.show(previous)
        source.present_read(surface, read)
        assert surface.thread_activity.row is previous


async def test_foreign_read_presents_the_real_stored_thread(workspace):
    foreign = Comms(workspace.roots.attempt / "foreign-wire")
    foreign.registry.declare(
        foreign.registry.new_thread(
            "peer", frozenset(), str(workspace.project), created_at=10.0
        )
    )
    async with workspace.app() as ui:
        app, _ = ui.textual
        source = ForeignStatusThread(foreign.root, "peer")
        surface = ForeignStatusSurface(source)
        await app.selected_session.mount(surface)
        await source.read_foreign_thread(surface)
        assert surface.thread_activity.row == ThreadStatusModel.known(
            "peer", foreign.views.thread_presentations(("peer",)).read("peer")
        )
