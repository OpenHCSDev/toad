"""Textual-facing: tab closing. A tab's logical lifetime ends without removing its saved thread."""
from dataclasses import dataclass
from functools import partial

from agent_comms.launch_root import LaunchRoot
from toad.comms_root import FailedObservation, UnselectedRoute
from toad.core.events import ObservedServiceChanged
from support.applications import record_notifications
from toad.preferences import SETTINGS
from toad.screens.main import MainScreen
from toad.widgets.session_tabs import SessionTabClose


@dataclass
class ObservationChanges:
    count: int = 0

    def received(self, event, subscription):
        self.count += 1


async def test_closing_a_tab_keeps_its_thread_and_reports_no_error(workspace):
    threads = [workspace.thread(name, title=name) for name in ("first", "second")]
    root = str(workspace.roots.wire)
    with LaunchRoot.from_path(root).selected():
        async with workspace.app(size=(120, 40), session=False) as ui:
            app, pilot = ui.textual
            record_notifications(app)

            def failure(error):
                return FailedObservation(error, UnselectedRoute(), access=app.coordination_access)

            assert failure(ValueError("same")) == failure(ValueError("same"))
            assert failure(ValueError("same")) != failure(RuntimeError("same"))
            missing = failure(OSError(2, "missing", "one"))
            assert missing == failure(OSError(2, "missing", "one"))
            assert missing != failure(OSError(2, "missing", "two"))
            assert missing.failed(OSError(2, "missing", "one"), UnselectedRoute()) is missing

            access = app.coordination_access
            if access.route_task is not None:
                await access.route_task
            changes = ObservationChanges()
            with access.events.subscribe(ObservedServiceChanged, changes.received):
                # The app remains bound to its original root. Selecting another
                # process root makes its real route capture fail, without mocks.
                with LaunchRoot.from_path(workspace.project / "other-root").selected():
                    failed = await access.preparation.run_thread(access.open_current)
                    repeated = await access.preparation.run_thread(access.open_current)
                    await ui.step()
                    assert isinstance(failed, FailedObservation)
                    assert failed == repeated and failed is repeated
                    assert changes.count == 1
            await access.route_changed()

            app.saved_settings.set(SETTINGS.sidebar.show_stopped, True)
            modes = []
            for thread in threads:
                owner = thread.incarnation
                details = await app.session_navigation.new(
                    partial(MainScreen.from_thread, workspace.project, root, owner),
                    title=thread.name, original=(root, owner))
                modes.append(details.mode_name)
                await app.selected_session.wait_content_ready()
            first, second = modes
            await ui.until(lambda: "second" in app.coordination_access.observation.sidebar.threads.rows,
                           why="both saved threads to appear in the thread list")

            async def close_selected(mode):
                closing_view = app.workspace_sessions.views[mode]
                assert await pilot.click(app.screen.query_one(f"#close-{mode}", SessionTabClose))
                await ui.until(lambda: not closing_view.is_attached,
                               why="the closed tab's view to finish removal")
                await ui.step()
                assert app.selected_mode == first
                assert [entry.mode for entry in app.session_navigation.members] == [first]
                assert workspace.comms.registry.require("second").incarnation == threads[1].incarnation
                assert "second" in app.coordination_access.observation.sidebar.threads.rows
                assert not [notification for notification in app._notifications
                            if notification.severity == "error"]

            await close_selected(second)
            history = await ui.open_direct("second", actor="first", owner=first)
            await close_selected(history)
