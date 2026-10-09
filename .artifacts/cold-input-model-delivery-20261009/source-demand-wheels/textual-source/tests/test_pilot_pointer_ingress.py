import asyncio

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.geometry import Offset
from textual.widgets import Static
from tests.test_pointer_capture_order import send_pointer


class PointerCell(Static):
    ALLOW_SELECT = False


class PointerApp(App):
    CSS = "PointerCell {width: 10; height: 3;}"

    def __init__(self):
        super().__init__()
        self.delivered = []

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield PointerCell("original", id="target")
            yield PointerCell("outside", id="outside")

    def on_click(self, event):
        self.delivered.append(
            (event.widget.id, event.chain, event.shift, event.meta, event.ctrl)
        )


async def test_real_run_async_pilot_and_driver_share_click_chain_and_modifiers():
    app = PointerApp()

    async def drive(pilot):
        target = app.query_one("#target")
        # Driver and Pilot must update the same App-owned press/chain facts.
        await pilot.pause()
        point = target.region.offset + Offset(1, 1)
        send_pointer(app, events.MouseDown, point)
        send_pointer(app, events.MouseUp, point)
        await pilot.pause()
        assert await pilot.click(
            target, offset=(1, 1), shift=True, meta=True, control=True
        )
        assert app.delivered == [
            ("target", 1, False, False, False),
            ("target", 2, True, True, True),
        ]
        # An unmatched second release must not borrow the consumed press.
        send_pointer(app, events.MouseUp, point)
        await pilot.pause()
        assert len(app.delivered) == 2
        app.exit()

    await asyncio.wait_for(
        app.run_async(headless=True, size=(40, 8), auto_pilot=drive), 10
    )
    assert app._exception is None
    assert app._task is None


async def test_pilot_click_refuses_when_press_moves_original_target():
    class Moving(PointerCell):
        def on_mouse_down(self, event):
            self.styles.offset = (12, 0)

    class MovingApp(PointerApp):
        def compose(self):
            yield Moving("original", id="target")

    app = MovingApp()
    async with app.run_test(size=(40, 8)) as pilot:
        target = app.query_one("#target")
        assert not await pilot.click(target, offset=(1, 1))
        assert target.region.x == 12
        assert app.delivered == []


async def test_mouse_down_result_uses_final_packet_after_hover_changes_layout():
    class Moving(PointerCell):
        def on_mouse_move(self, event):
            self.styles.offset = (12, 0)

    class MovingApp(PointerApp):
        def compose(self):
            yield Moving("original", id="target")

    app = MovingApp()
    async with app.run_test(size=(40, 8)) as pilot:
        target = app.query_one("#target")
        assert not await pilot.mouse_down(target, offset=(1, 1))
        assert app._mouse_down_widget is app.screen
        assert target.region.x == 12


async def test_mouse_up_result_uses_capture_rather_than_widget_under_pointer():
    class Capturing(PointerCell):
        def on_mouse_down(self, event):
            self.capture_mouse()

        def on_mouse_up(self, event):
            self.release_mouse()
            self.app.released = event.widget

    class CaptureApp(PointerApp):
        def compose(self):
            with Horizontal():
                yield Capturing("original", id="target")
                yield PointerCell("outside", id="outside")

    app = CaptureApp()
    async with app.run_test(size=(40, 8)) as pilot:
        target = app.query_one("#target")
        assert await pilot.mouse_down(target, offset=(1, 1))
        assert not await pilot.mouse_up("#outside", offset=(1, 1))
        assert app.released is target
        assert app.mouse_captured is None
        assert app.delivered == []


async def test_click_receipt_survives_recipient_removal_after_delivery():
    class Removing(PointerCell):
        async def on_click(self, event):
            self.app.clicked = event.widget
            await self.remove()

    class RemovingApp(PointerApp):
        def compose(self):
            yield Removing("original", id="target")

    app = RemovingApp()
    async with app.run_test(size=(40, 8)) as pilot:
        target = app.query_one("#target")
        assert await pilot.click(target, offset=(1, 1))
        assert app.clicked is target
        assert not target.is_attached
        assert target._task is None


async def test_background_screen_delivery_keeps_raw_app_completion():
    class BlankApp(PointerApp):
        def compose(self):
            return ()

    app = BlankApp()
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        assert app.get_widget_at(30, 7)[0] is app.screen
        assert await pilot.click(app.screen, offset=(30, 7))
        assert await pilot.hover(app.screen, offset=(30, 7))
        assert app.delivered == [(app.screen.id, 1, False, False, False)]
