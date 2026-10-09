import asyncio

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.geometry import Offset
from textual.message_pump import MessagePump
from textual.widgets import Static

from tests.test_pointer_capture_order import send_pointer


async def test_run_async_driver_burst_owns_bubbling_pointer_until_terminal():
    delivered, root_deliveries, child_tasks = [], [], []
    wheel = asyncio.Event()

    class Handle(Static):
        ALLOW_SELECT = False

        def on_mouse_down(self, event):
            self.capture_mouse()
            delivered.append("down")

        def on_mouse_move(self, event):
            delivered.append("move")

        def on_mouse_up(self, event):
            self.release_mouse()
            delivered.append("up")

    class Body(Static):
        def on_mouse_scroll_up(self, event):
            delivered.append("wheel")
            wheel.set()

    class RealEntryApp(App[str]):
        CSS = "Handle {width: 6; height: 3;} Body {width: 20; height: 3;}"
        startup_task = None

        def compose(self) -> ComposeResult:
            with Horizontal():
                yield Handle("handle")
                yield Body("body")

        def on_mount(self):
            self.startup_task = self.task
            assert self.task is asyncio.current_task()

        def on_mouse_down(self, event):
            root_deliveries.append("down")

        def on_mouse_move(self, event):
            root_deliveries.append("move")

        def on_mouse_up(self, event):
            root_deliveries.append("up")

        def on_mouse_scroll_up(self, event):
            root_deliveries.append("wheel")

    app = RealEntryApp()

    async def drive(pilot):
        await pilot.pause()
        handle, body = app.query_one(Handle), app.query_one(Body)
        child_tasks.extend([handle.task, body.task, app.screen.task])
        assert app.task is app.startup_task
        down = handle.region.offset + Offset(1, 1)
        away = body.region.offset + Offset(3, 1)
        send_pointer(app, events.MouseDown, down)
        send_pointer(app, events.MouseMove, away)
        send_pointer(app, events.MouseUp, away)
        send_pointer(app, events.MouseScrollUp, away, button=0)
        await asyncio.wait_for(wheel.wait(), 5)
        await pilot.pause()
        assert app.mouse_captured is None
        assert delivered == ["down", "move", "up", "wheel"]
        assert root_deliveries == delivered
        app.exit("complete")

    run_task = asyncio.create_task(
        app.run_async(headless=True, size=(40, 8), auto_pilot=drive)
    )
    result = await asyncio.wait_for(run_task, 10)
    assert result == "complete"
    assert app._exception is None
    assert app._task is None
    assert app.startup_task is run_task
    assert run_task.done()
    assert all(task.done() for task in child_tasks)


async def test_run_async_startup_failure_releases_shared_task():
    class FailedStartup(App):
        observed_task = None

        def on_mount(self):
            self.observed_task = self.task
            assert self.task is asyncio.current_task()
            raise RuntimeError("original startup failure")

    app = FailedStartup()
    run_task = asyncio.create_task(app.run_async(headless=True, size=(20, 4)))
    await asyncio.wait_for(run_task, 5)
    assert isinstance(app._exception, RuntimeError)
    assert app._exception.args == ("original startup failure",)
    assert app._task is None
    assert not app.is_running
    assert app.observed_task is run_task
    assert run_task.done()


async def test_run_async_cancel_releases_pump_and_children():
    child_tasks = []

    class CancelledEntry(App):
        def compose(self) -> ComposeResult:
            yield Static("original source")

    app = CancelledEntry()

    async def cancel(pilot):
        await pilot.pause()
        child_tasks.extend([app.screen.task, app.query_one(Static).task])
        app.task.cancel()

    run_task = asyncio.create_task(
        app.run_async(headless=True, size=(20, 4), auto_pilot=cancel)
    )
    await asyncio.wait_for(run_task, 5)
    assert app._task is None
    assert not app.is_running
    assert all(task.done() for task in child_tasks)


async def test_eager_completed_pump_is_not_reenrolled_after_release():
    class ImmediatePump(MessagePump):
        async def _process_messages_body(self, **kwargs):
            assert self.task is asyncio.current_task()

    app = App()

    async def drive(pilot):
        pump = ImmediatePump()
        pump._start_messages()
        # run_async enables the real interpreter's eager factory when present.
        # On older interpreters, let the scheduled original task enter and exit.
        if pump._task is not None:
            await pump.task
        assert pump._task is None
        app.exit()

    await asyncio.wait_for(app.run_async(headless=True, auto_pilot=drive), 5)
    assert app._task is None
