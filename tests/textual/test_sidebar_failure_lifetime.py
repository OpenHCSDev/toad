"""An observer failure is a transition, not a recursively repeated interest response."""

from contextlib import asynccontextmanager

from toad.comms_root import UnselectedRoute
from toad.widgets.comms_sidebar import CommsSidebar
from toad.sidebar_model_view import FailedSidebarState


class FailNextInterest:
    """A real subscription callback can fail while the previous presentation is applying."""

    def __init__(self, access):
        self.access = access
        self.original = access.show_sidebar
        self.pending = True

    def show_sidebar(self, view, shown):
        if self.pending and shown:
            self.pending = False
            failed = self.access.observation.failed(
                OSError("failed during sidebar interest"), UnselectedRoute())
            view.bind_failed_observation(failed)
        self.original(view, shown)


@asynccontextmanager
async def showing_sidebar(workspace):
    workspace.thread("worker", running=True)
    async with workspace.app(session=False) as ui:
        panel = await ui.revealed(ui.app.workspace_chrome.channels)
        sidebar = panel.query_one(CommsSidebar)
        await ui.until(lambda: sidebar.model_state.shows_model(), why="the original sidebar model")
        yield ui, sidebar


async def test_failed_sidebar_interest_does_not_repeat_the_failure_transition(workspace):
    async with showing_sidebar(workspace) as (ui, sidebar):
        app, pilot = ui.textual
        access = app.coordination_access
        failed = access.observation.failed(OSError("observer ended"), UnselectedRoute())
        await ui.until(lambda: isinstance(sidebar.model_state, FailedSidebarState),
                       why="the failure transition to reach the real sidebar")
        assert "observer ended" in str(sidebar.unavailable.render())
        state = sidebar.model_state
        failed.observe_sidebar(access.sidebar_request())
        assert sidebar.model_state is state, "An interest change rebound an already failed view"
        await pilot.press("tab")
        await access.route_changed()
        await ui.until(lambda: sidebar.model_state.shows_model(), why="the sidebar to recover")


async def test_reentrant_sidebar_failure_cannot_restore_an_unsubscribed_state(workspace, monkeypatch):
    async with showing_sidebar(workspace) as (ui, sidebar):
        access = ui.app.coordination_access
        registration = FailNextInterest(access)
        with monkeypatch.context() as patch:
            patch.setattr(access, "show_sidebar", registration.show_sidebar)
            sidebar.present()
            assert isinstance(sidebar.model_state, FailedSidebarState), (
                "The old present() result overwrote a newer failure transition")
        await ui.step()
        await access.route_changed()
        await ui.until(lambda: sidebar.model_state.shows_model(), why="the reentrant failure to recover")
        sidebar.stop_showing()
        sidebar.stop_showing()
        await ui.step()
