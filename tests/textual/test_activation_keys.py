"""Remapped keyboard and primary pointer input invoke the original callback once."""
import asyncio

from textual.app import App, ComposeResult
from textual.document._editing import EditingMode
from textual.widgets import Static

from toad.widget_actions import ActivationKeys, ActivateAction


class CallbackControl(ActivationKeys, Static, can_focus=True):
    DEFAULT_CSS = "CallbackControl { height: 3; width: 20; }"

    def __init__(self, callback, label):
        super().__init__(label)
        self.callback = callback

    @property
    def primary_activation(self):
        return self.callback


async def test_remapped_activation_and_primary_click_await_sync_and_async_effects():
    calls = []

    def sync_effect():
        calls.append("sync")

    async def async_effect():
        await asyncio.sleep(0)
        calls.append("async")

    class Controls(App):
        def compose(self) -> ComposeResult:
            yield CallbackControl(sync_effect, "Synchronous")
            yield CallbackControl(async_effect, "Asynchronous")

    app = Controls()
    async with app.run_test() as pilot:
        sync_control, async_control = app.query(CallbackControl)
        app.set_keymap({ActivateAction.binding_id(EditingMode): "f9"})
        sync_control.focus()
        await pilot.press("enter", "space")
        assert calls == []
        await pilot.press("f9")
        assert calls == ["sync"]
        await pilot.click(sync_control, button=3)
        assert calls == ["sync"]
        await pilot.click(sync_control)
        assert calls == ["sync", "sync"]
        async_control.focus()
        await pilot.press("f9")
        await pilot.click(async_control)
        assert calls == ["sync", "sync", "async", "async"]
