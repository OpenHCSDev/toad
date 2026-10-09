"""Moving a retained presentation changes ancestry without restarting its lifetime."""

import asyncio

import pytest

from textual.app import App
from textual.containers import VerticalGroup
from textual.screen import Screen
from textual.selection import SELECT_ALL
from textual.widget import WidgetError
from textual.widgets import Static


class Retained(VerticalGroup):
    mounts = 0
    unmounts = 0

    def on_mount(self):
        self.mounts += 1

    def on_unmount(self):
        self.unmounts += 1


async def test_reparent_preserves_widget_tasks_and_updates_native_ancestry():
    class Example(App):
        CSS = "#left Static { color: red; } #right Static { color: blue; }"

    app = Example()
    async with app.run_test() as pilot:
        first, second = VerticalGroup(id="left"), VerticalGroup(id="right")
        panel = Retained(Static("unchanged model", id="body"), id="shared")
        await app.mount(first, second)
        await first.mount(panel)
        await pilot.pause()
        child = panel.query_one("#body", Static)
        tasks = panel._task, child._task
        red = child.styles.color
        app.screen.selections = {child: SELECT_ALL}
        first.query_one("#shared")  # Warm the native selector cache.
        panel.reparent(second)
        await pilot.pause()
        assert panel.parent is second and panel.screen is app.screen
        assert not first.query("#shared") and second.query_one("#shared") is panel
        assert panel.query_one("#body") is child and child.content == "unchanged model"
        assert app.screen.selections == {child: SELECT_ALL}
        assert (panel._task, child._task) == tasks
        assert panel.mounts == 1 and panel.unmounts == 0
        assert child.styles.color != red
        await first.remove()
        assert panel.is_attached and not panel._closed
        await panel.remove()
        assert panel.unmounts == 1


async def test_reparent_moves_screen_focus_and_selection_without_stale_scene_owners():
    class FocusedText(Static, can_focus=True):
        pass

    app = App()
    async with app.run_test() as pilot:
        app.add_mode("one", Screen)
        app.add_mode("two", Screen)
        await app.switch_mode("one")
        previous = app.screen
        panel = Retained(FocusedText("selected model"), id="shared")
        await previous.mount(panel)
        await pilot.pause()
        leaf = panel.query_one(FocusedText)
        leaf.focus()
        await pilot.pause()
        previous.selections = {leaf: SELECT_ALL}
        previous._compositor.full_map
        await app.switch_mode("two")
        destination = app.screen
        panel.reparent(destination)
        await pilot.pause()
        assert leaf.screen is destination
        assert previous.focused is None and destination.focused is leaf
        assert leaf not in previous.selections
        assert destination.selections[leaf] == SELECT_ALL
        assert "selected model" in destination.get_selected_text()
        assert panel not in previous._compositor.widgets
        assert leaf not in previous._compositor._full_map
        await app.remove_mode("one")
        assert panel.is_attached and not panel._closed


async def test_reparent_rejects_cycles_unmounted_targets_and_duplicate_ids_atomically():
    app = App()
    async with app.run_test() as pilot:
        panel = Retained(VerticalGroup(id="nested"), id="shared")
        source = VerticalGroup(panel)
        target = VerticalGroup(Static("already here", id="shared"))
        await app.mount(source, target)
        await pilot.pause()
        for invalid in (panel, panel.query_one("#nested"), VerticalGroup(), target):
            with pytest.raises(WidgetError):
                panel.reparent(invalid)
            assert panel.parent is source and source.query_one("#shared") is panel
            assert panel.mounts == 1 and panel.unmounts == 0


async def test_reparent_preserves_order_and_transfers_pending_frame_callbacks():
    app = App()
    async with app.run_test() as pilot:
        app.add_mode("one", Screen)
        app.add_mode("two", Screen)
        await app.switch_mode("one")
        previous = app.screen
        panel = Retained(Static("content"))
        await previous.mount(panel)
        await app.switch_mode("two")
        destination = app.screen
        marker = Static("after")
        await destination.mount(marker)
        received = []
        callback_completed = asyncio.Event()

        def after_paint():
            received.append(panel.screen)
            callback_completed.set()

        previous._invoke_later(after_paint, panel)
        panel.reparent(destination, before=marker)
        assert list(destination.children) == [panel, marker]
        assert all(sender is not panel for _, sender in previous._callbacks)
        assert any(sender is panel for _, sender in destination._callbacks)
        await pilot.pause()
        # pause schedules the paint's call_next callbacks; it does not await
        # them. Observe the original transferred callback, not loop idleness.
        await callback_completed.wait()
        assert received == [destination]


async def test_reparent_during_mouse_capture_is_rejected_without_detaching():
    app = App()
    async with app.run_test() as pilot:
        child = Static("drag target")
        source = Retained(child)
        destination = VerticalGroup()
        await app.mount(source, destination)
        await pilot.pause()
        child.capture_mouse()
        with pytest.raises(WidgetError):
            source.reparent(destination)
        assert source.parent is app.screen and child.parent is source
        assert app.mouse_captured is child
        child.release_mouse()
        source.reparent(destination)
        assert source.parent is destination
