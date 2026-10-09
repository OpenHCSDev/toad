import asyncio

import pytest

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.geometry import Offset
from textual.widgets import Input, Static, TextArea


def send_pointer(app, kind, point, button=1):
    # Exercise real driver ingress, including sender and button ownership.
    app._driver.process_message(kind(None, *point, 0, 0, button, False, False, False))


async def test_driver_burst_waits_for_press_capture_and_routes_release_before_wheel():
    entered, release = asyncio.Event(), asyncio.Event()
    delivered = []

    class Handle(Static):
        ALLOW_SELECT = False

        async def on_mouse_down(self, event):
            event.stop()
            entered.set()
            await release.wait()
            self.capture_mouse()
            delivered.append(("down", event.screen_offset))

        def on_mouse_move(self, event):
            event.stop()
            delivered.append(("move", event.screen_offset))

        def on_mouse_up(self, event):
            event.stop()
            delivered.append(("up", event.screen_offset))
            self.release_mouse()

    class Body(Static):
        def on_mouse_scroll_up(self, event):
            event.stop()
            delivered.append(("wheel", event.screen_offset))

    class PointerApp(App):
        CSS = "Handle {width: 6; height: 3;} Body {width: 20; height: 3;}"

        def compose(self) -> ComposeResult:
            with Horizontal():
                yield Handle("handle")
                yield Body("body")

    app = PointerApp()
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        handle = app.query_one(Handle)
        body = app.query_one(Body)
        down = handle.region.offset + Offset(1, 1)
        move = body.region.offset + Offset(2, 1)
        up = move + Offset(1, 0)
        send_pointer(app, events.MouseDown, down)
        send_pointer(app, events.MouseMove, move)
        send_pointer(app, events.MouseUp, up)
        send_pointer(app, events.MouseScrollUp, move, button=0)
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert not delivered
            assert app.mouse_position == down
        finally:
            release.set()
        await pilot.pause()
        assert delivered == [("down", down), ("move", move), ("up", up), ("wheel", move)]
        assert app.mouse_captured is None


async def test_driver_burst_waits_for_bubbled_parent_capture():
    delivered = []

    class CaptureParent(VerticalGroup):
        ALLOW_SELECT = False

        def on_mouse_down(self, event):
            event.stop()
            self.capture_mouse()
            delivered.append("down")

        def on_mouse_move(self, event):
            event.stop()
            delivered.append("move")

        def on_mouse_up(self, event):
            event.stop()
            self.release_mouse()
            delivered.append("up")

    class PointerApp(App):
        CSS = "CaptureParent {width: 6; height: 3;} #outside {width: 20; height: 3;}"

        def compose(self) -> ComposeResult:
            with Horizontal():
                with CaptureParent():
                    yield Static("child")
                yield Static("outside", id="outside")

    app = PointerApp()
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        parent = app.query_one(CaptureParent)
        outside = app.query_one("#outside")
        send_pointer(app, events.MouseDown, parent.region.offset + Offset(1, 0))
        send_pointer(app, events.MouseMove, outside.region.offset + Offset(2, 1))
        send_pointer(app, events.MouseUp, outside.region.offset + Offset(3, 1))
        await pilot.pause()
        assert delivered == ["down", "move", "up"]
        assert app.mouse_captured is None


@pytest.mark.parametrize("editor", [Input, TextArea])
async def test_original_editor_capture_releases_after_driver_burst(editor):
    class EditorApp(App):
        CSS = "#editor {width: 12; height: 3;} #outside {width: 20; height: 3;}"

        def compose(self) -> ComposeResult:
            with Horizontal():
                yield editor("original text", id="editor")
                yield Static("outside", id="outside")

    app = EditorApp()
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        target = app.query_one("#editor")
        outside = app.query_one("#outside")
        down = target.content_region.offset + Offset(1, 0)
        away = outside.content_region.offset + Offset(3, 0)
        send_pointer(app, events.MouseDown, down)
        send_pointer(app, events.MouseMove, away)
        send_pointer(app, events.MouseUp, away)
        await pilot.pause()
        assert not target._selecting
        assert app.mouse_captured is None
        # Initial Input panning and TextArea wrapping own the exact endpoints.
        # A routed drag must select text and terminate without editing it.
        assert target.selected_text
        assert (target.value if editor is Input else target.text) == "original text"


async def test_filtered_pointer_delivery_does_not_hold_ingress():
    app = App()
    async with app.run_test(size=(40, 8)) as pilot:
        disabled = Static("disabled", disabled=True)
        await app.mount(disabled)
        await pilot.pause()
        point = disabled.region.offset
        send_pointer(app, events.MouseDown, point)
        send_pointer(app, events.MouseUp, point)
        await pilot.pause()
        assert app.mouse_position == point
        assert app.mouse_captured is None


async def test_pointer_receiver_self_removal_releases_original_delivery():
    class Retiring(Static):
        ALLOW_SELECT = False

        async def on_mouse_down(self, event):
            event.stop()
            await self.remove()

    app = App()
    async with app.run_test(size=(40, 8)) as pilot:
        target = Retiring("retiring")
        await app.mount(target)
        await pilot.pause()
        send_pointer(app, events.MouseDown, target.region.offset)
        send_pointer(app, events.MouseMove, Offset(20, 4))
        send_pointer(app, events.MouseUp, Offset(21, 4))
        await pilot.pause()
        assert not target.is_attached
        assert target._task is None
        assert app.mouse_position == Offset(21, 4)
        assert app.mouse_captured is None


@pytest.mark.parametrize('latest_position', [False, True])
async def test_captured_absolute_motion_replacement_preserves_gesture_boundaries(latest_position):
    entered, release = asyncio.Event(), asyncio.Event()
    delivered = []

    class Handle(Static):
        ALLOW_SELECT = False

        def can_replace_mouse_move(self, event, pending):
            return latest_position and event.button == 1

        async def on_mouse_down(self, event):
            event.stop()
            entered.set()
            await release.wait()
            self.capture_mouse()
            delivered.append(('down', event.screen_x))

        def on_mouse_move(self, event):
            event.stop()
            delivered.append(('move', event.screen_x, event.shift))

        def on_mouse_up(self, event):
            event.stop()
            delivered.append(('up', event.screen_x))
            self.release_mouse()

        def on_mouse_scroll_up(self, event):
            event.stop()
            delivered.append(('wheel', event.screen_x))

    class PointerApp(App):
        CSS = 'Handle {width: 30; height: 3;}'

        def compose(self):
            yield Handle('handle')

    app = PointerApp()
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        handle = app.query_one(Handle)
        send_pointer(app, events.MouseDown, Offset(1, 1))
        await asyncio.wait_for(entered.wait(), 5)
        for x, shift in [(2, False), (3, False), (4, True), (5, True)]:
            app._driver.process_message(events.MouseMove(None, x, 1, 1, 0, 1, shift, False, False))
        send_pointer(app, events.MouseScrollUp, Offset(6, 1), button=0)
        for x in (7, 8):
            send_pointer(app, events.MouseMove, Offset(x, 1))
        send_pointer(app, events.MouseUp, Offset(9, 1))
        for x in (10, 11):
            send_pointer(app, events.MouseMove, Offset(x, 1), button=0)
        release.set()
        await pilot.pause()
        moves = [('move', 3, False), ('move', 5, True)] if latest_position else [
            ('move', 2, False), ('move', 3, False), ('move', 4, True), ('move', 5, True)]
        second = [('move', 8, False)] if latest_position else [
            ('move', 7, False), ('move', 8, False)]
        assert delivered == [('down', 1), *moves, ('wheel', 6), *second,
                             ('up', 9), ('move', 10, False), ('move', 11, False)]
        assert app.mouse_captured is None
        assert app.mouse_position == Offset(11, 1)


async def test_captured_motion_keeps_each_owned_delivery_completion():
    entered, release = asyncio.Event(), asyncio.Event()
    delivered = []

    class Handle(Static):
        ALLOW_SELECT = False

        def can_replace_mouse_move(self, event, pending):
            return True

        async def on_mouse_down(self, event):
            event.stop()
            entered.set()
            await release.wait()
            self.capture_mouse()

        def on_mouse_move(self, event):
            event.stop()
            delivered.append(event.screen_x)

    class PointerApp(App):
        CSS = 'Handle {width: 30; height: 3;}'

        def compose(self):
            yield Handle('handle')

    app = PointerApp()
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        send_pointer(app, events.MouseDown, Offset(1, 1))
        await asyncio.wait_for(entered.wait(), 5)
        completions = [app._post_message_and_wait(
            events.MouseMove(None, x, 1, 1, 0, 1, False, False, False).set_sender(app))
            for x in (2, 3, 4)]
        release.set()
        await asyncio.wait_for(asyncio.gather(*completions), 5)
        await pilot.pause()
        assert delivered == [2, 3, 4]
        app.capture_mouse(None)
