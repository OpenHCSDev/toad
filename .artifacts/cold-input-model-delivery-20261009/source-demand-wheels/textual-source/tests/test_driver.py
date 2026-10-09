import asyncio
import threading

from textual import on
from textual.app import App
from textual.binding import Binding
from textual.events import Click, Key, MouseDown, MouseUp, Paste
from textual.widgets import Button, Input


async def test_driver_input_enters_native_queue_in_one_loop_handoff():
    """An extra relay task lets an entire ready render overtake input ingress."""
    posted = []

    class InputApp(App):
        def compose(self):
            yield Input()

        def post_message(self, message):
            if isinstance(message, Key):
                posted.append((message.key, threading.get_ident()))
            return super().post_message(message)

    app = InputApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        loop = asyncio.get_running_loop()
        checkpoint = loop.create_future()
        owner_thread = threading.get_ident()

        def send():
            app._driver.send_message(Key("a", "a"))
            app._driver.send_message(Key("b", "b"))
            loop.call_soon_threadsafe(lambda: checkpoint.set_result(tuple(posted)))

        sender = threading.Thread(target=send)
        sender.start()
        # The sender only enqueues thread-safe callbacks; synchronize the test
        # so the observation has a deterministic place in that callback order.
        sender.join(timeout=1)
        assert not sender.is_alive()
        observed = await asyncio.wait_for(checkpoint, 1)
        assert observed == (("a", owner_thread), ("b", owner_thread))
        await pilot.pause()
        assert app.query_one(Input).value == "ab"


async def test_driver_keeps_native_priority_bindings_focus_and_paste_routing():
    class InputApp(App):
        BINDINGS = [Binding("ctrl+p", "priority", priority=True)]
        priority_called = False

        def compose(self):
            yield Input(id="first")
            yield Input(id="second")

        def action_priority(self):
            self.priority_called = True

    app = InputApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for event in (Key("a", "a"), Key("ctrl+p", None), Key("tab", "\t"), Paste("bc")):
            await asyncio.to_thread(app._driver.send_message, event)
            await pilot.pause()
        assert app.priority_called
        assert app.query_one("#first", Input).value == "a"
        assert app.query_one("#second", Input).value == "bc"


async def test_driver_mouse_down_up_click():
    """Mouse down and up should issue a click."""

    class MyApp(App):
        messages = []

        @on(Click)
        @on(MouseDown)
        @on(MouseUp)
        def handle(self, event):
            self.messages.append(event)

    app = MyApp()
    async with app.run_test() as pilot:
        app._driver.process_message(MouseDown(None, 0, 0, 0, 0, 1, False, False, False))
        app._driver.process_message(MouseUp(None, 0, 0, 0, 0, 1, False, False, False))
        await pilot.pause()
        assert len(app.messages) == 3
        assert isinstance(app.messages[0], MouseDown)
        assert isinstance(app.messages[1], MouseUp)
        assert isinstance(app.messages[2], Click)


async def test_driver_mouse_down_up_click_widget():
    """Mouse down and up should issue a click when they're on a widget."""

    class MyApp(App):
        messages = []

        def compose(self):
            yield Button()

        def on_button_pressed(self, event):
            self.messages.append(event)

    app = MyApp()
    async with app.run_test() as pilot:
        app._driver.process_message(MouseDown(None, 0, 0, 0, 0, 1, False, False, False))
        app._driver.process_message(MouseUp(None, 0, 0, 0, 0, 1, False, False, False))
        await pilot.pause()
        assert len(app.messages) == 1


async def test_driver_mouse_down_drag_inside_widget_up_click():
    """Mouse down and up should issue a click, even if the mouse moves but remains
    inside the same widget."""

    class MyApp(App):
        messages = []

        def compose(self):
            yield Button()

        def on_button_pressed(self, event):
            self.messages.append(event)

    app = MyApp()
    button_width = 16
    button_height = 3
    async with app.run_test() as pilot:
        # Sanity check
        width, height = app.query_one(Button).region.size
        assert (width, height) == (button_width, button_height)

        # Mouse down on the button, then move the mouse inside the button, then mouse up.
        app._driver.process_message(MouseDown(None, 0, 0, 0, 0, 1, False, False, False))
        app._driver.process_message(
            MouseUp(
                None,
                button_width - 1,
                button_height - 1,
                button_width - 1,
                button_height - 1,
                1,
                False,
                False,
                False,
            )
        )
        await pilot.pause()
        # A click should still be triggered.
        assert len(app.messages) == 1


async def test_driver_mouse_down_drag_outside_widget_up_click():
    """Mouse down and up don't issue a click if the mouse moves outside of the initial widget."""

    class MyApp(App):
        messages = []

        def compose(self):
            yield Button()

        def on_button_pressed(self, event):
            self.messages.append(event)

    app = MyApp()
    button_width = 16
    button_height = 3
    async with app.run_test() as pilot:
        # Sanity check
        width, height = app.query_one(Button).region.size
        assert (width, height) == (button_width, button_height)

        # Mouse down on the button, then move the mouse outside the button, then mouse up.
        app._driver.process_message(MouseDown(None, 0, 0, 0, 0, 1, False, False, False))
        app._driver.process_message(
            MouseUp(
                None,
                button_width + 1,
                button_height + 1,
                button_width + 1,
                button_height + 1,
                1,
                False,
                False,
                False,
            )
        )
        await pilot.pause()
        assert len(app.messages) == 0
