import asyncio

from textual import events
from textual.app import App
from textual.containers import VerticalScroll
from textual.geometry import Offset
from textual.screen import Screen
from textual.widgets import Static


def pointer(app, kind, point, button):
    # Real driver ingress, including its pressed-button tracking.
    app._driver.process_message(
        kind(None, *point, 0, 1, button, False, False, False)
    )


class HistoryApp(App):
    CSS = "#history {width: 30; height: 6;} Static {height: 1;}"

    def __init__(self):
        super().__init__()
        self.selection_completions = 0

    def compose(self):
        with VerticalScroll(id="history"):
            for index in range(50):
                yield Static(f"original row {index:02}", id=f"row-{index}")

    def on_text_selected(self):
        self.selection_completions += 1


async def positioned(app, pilot):
    # The mounted run_async callback precedes its first resized arrangement.
    # Borrow the original publication before acquiring scroll coordinates.
    await pilot.pause()
    history = app.query_one("#history", VerticalScroll)
    assert history.max_scroll_y > 20
    history.scroll_to(y=20, animate=False, immediate=True)
    await pilot.pause()
    assert history.scroll_y == 20
    first_row = app.query_one("#row-21")
    first = first_row.region.offset + Offset(1, 0)
    assert app.get_widget_at(*first)[0] is first_row
    last = app.query_one("#row-23").region.offset + Offset(4, 0)
    edge = Offset(first.x, history.content_region.bottom - 1)
    assert app.screen.get_widget_and_offset_at(*edge)[0] is not None
    return history, first, last, edge


async def test_secondary_edge_drag_does_not_acquire_selection_or_auto_scroll():
    app = HistoryApp()
    async with app.run_test(size=(40, 10)) as pilot:
        history, first, _, edge = await positioned(app, pilot)
        original_scroll = history.scroll_y
        pointer(app, events.MouseDown, first, 3)
        pointer(app, events.MouseMove, edge, 3)
        await pilot.pause()
        assert app.screen._mouse_down_offset is None
        assert app.screen._select_state is None
        assert not app.screen._selecting
        assert app.screen._auto_select_scroll_timer is None
        pointer(app, events.MouseUp, edge, 3)
        await pilot.pause()
        assert history.scroll_y == original_scroll
        assert app.screen.get_selected_text() is None
        assert app.selection_completions == 0


async def test_secondary_release_preserves_primary_range_and_completion_owner():
    app = HistoryApp()
    async with app.run_test(size=(40, 10)) as pilot:
        _, first, last, _ = await positioned(app, pilot)
        pointer(app, events.MouseDown, first, 1)
        pointer(app, events.MouseMove, last, 1)
        await pilot.pause()
        state = app.screen._select_state
        text = app.screen.get_selected_text()
        assert state is not None and text
        pointer(app, events.MouseDown, first, 3)
        pointer(app, events.MouseUp, first, 3)
        await pilot.pause()
        assert app.screen._mouse_down_offset == first
        assert app.screen._select_state is state
        assert app.screen._selecting
        assert app.screen.get_selected_text() == text
        assert app.selection_completions == 0
        pointer(app, events.MouseUp, last, 1)
        await pilot.pause()
        assert not app.screen._selecting
        assert app.screen._mouse_down_offset is None
        assert app.screen.get_selected_text() == text
        assert app.selection_completions == 1


async def test_real_run_async_primary_edge_scroll_stops_without_projection_revival():
    app = HistoryApp()

    async def drive(pilot):
        history, first, _, edge = await positioned(app, pilot)
        original_scroll = history.scroll_y
        pointer(app, events.MouseDown, first, 1)
        pointer(app, events.MouseMove, edge, 1)
        await pilot.pause()
        assert app.screen._selecting
        assert app.screen._auto_select_scroll_timer is not None
        # Allow the original timer to execute; no replacement scroll callback.
        await pilot.pause(0.1)
        assert history.scroll_y > original_scroll
        pointer(app, events.MouseUp, edge, 1)
        await pilot.pause()
        screen = app.screen
        assert screen.get_selected_text()
        assert screen._select_state is not None
        assert not screen._selecting
        assert screen._auto_select_scroll_timer is None
        stopped_scroll = history.scroll_y
        screen._update_select()
        screen._flush_pending_selection()
        await pilot.pause(0.05)
        assert not screen._selecting
        assert screen._auto_select_scroll_timer is None
        assert history.scroll_y == stopped_scroll
        assert screen.get_selected_text()
        app.exit()

    await asyncio.wait_for(
        app.run_async(headless=True, size=(40, 10), auto_pilot=drive), 10
    )
    assert app._exception is None
    assert app._task is None


async def test_screen_suspend_retires_primary_scroll_but_retains_copyable_range():
    app = HistoryApp()
    async with app.run_test(size=(40, 10)) as pilot:
        history, first, _, edge = await positioned(app, pilot)
        pointer(app, events.MouseDown, first, 1)
        pointer(app, events.MouseMove, edge, 1)
        await pilot.pause()
        original = app.screen
        assert original._auto_select_scroll_timer is not None
        await app.push_screen(Screen(Static("Original modal")))
        await pilot.pause()
        assert original._mouse_down_offset is None
        assert not original._selecting
        assert original._auto_select_scroll_timer is None
        text = original.get_selected_text()
        stopped_scroll = history.scroll_y
        assert text
        await pilot.pause(0.05)
        assert history.scroll_y == stopped_scroll
        app.pop_screen()
        await pilot.pause()
        assert app.screen is original
        assert not original._selecting
        assert original.get_selected_text() == text
        assert original._auto_select_scroll_timer is None


async def test_right_capture_and_menu_keep_completed_primary_selection():
    class MenuRow(Static):
        def on_mouse_down(self, event):
            if event.button == 3:
                self.capture_mouse()

        def on_mouse_up(self, event):
            if event.button == 3:
                self.release_mouse()
                self.app.secondary_release = event.widget

        def on_click(self, event):
            if event.button == 3:
                self.app.push_screen(Screen(Static("Original right-click menu")))

    class MenuApp(HistoryApp):
        def compose(self):
            with VerticalScroll(id="history"):
                for index in range(50):
                    yield MenuRow(f"original row {index:02}", id=f"row-{index}")

    app = MenuApp()
    async with app.run_test(size=(40, 10)) as pilot:
        _, first, last, _ = await positioned(app, pilot)
        pointer(app, events.MouseDown, first, 1)
        pointer(app, events.MouseMove, last, 1)
        pointer(app, events.MouseUp, last, 1)
        await pilot.pause()
        original = app.screen
        selected_text = original.get_selected_text()
        state = original._select_state
        assert selected_text and state is not None
        row = app.query_one("#row-22", MenuRow)
        assert await pilot.click(row, button=3)
        assert app.secondary_release is row
        assert app.mouse_captured is None
        assert app.screen is not original
        assert original._select_state is state
        assert original.get_selected_text() == selected_text
        assert not original._selecting
        assert original._auto_select_scroll_timer is None
        assert app.selection_completions == 1
