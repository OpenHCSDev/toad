import asyncio

import pytest
import gc
from unittest.mock import patch
from weakref import ref

from textual.app import App, ComposeResult
from textual.containers import VerticalGroup, VerticalScroll
from textual.events import MouseMove, MouseScrollDown, MouseUp
from textual.geometry import Offset, Region
from textual.selection import Selection, SelectState
from textual.widgets import Static


@pytest.mark.parametrize(
    "text,selection,expected",
    [
        ("Hello", Selection(None, None), "Hello"),
        ("Hello\nWorld", Selection(None, None), "Hello\nWorld"),
        ("Hello\nWorld", Selection(Offset(0, 1), None), "World"),
        ("Hello\nWorld", Selection(None, Offset(5, 0)), "Hello"),
        ("Foo", Selection(Offset(0, 0), Offset(1, 0)), "F"),
        ("Foo", Selection(Offset(1, 0), Offset(2, 0)), "o"),
        ("Foo", Selection(Offset(0, 0), Offset(2, 0)), "Fo"),
        ("Foo", Selection(Offset(0, 0), None), "Foo"),
    ],
)
def test_extract(text: str, selection: Selection, expected: str) -> None:
    """Test Selection.extract"""
    assert selection.extract(text) == expected


async def test_double_width():
    """Test that selection works with double width characters."""

    TEXT = """😂❤️👍Select😊🙏😍\nme🔥💯😭😂❤️👍"""

    class TextSelectApp(App):
        def compose(self) -> ComposeResult:
            yield Static(TEXT)

    app = TextSelectApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await pilot.mouse_down(offset=(2, 0))
        await pilot.pause()
        assert await pilot.mouse_up(offset=(7, 1))
        selected_text = app.screen.get_selected_text()
        expected = "❤️👍Select😊🙏😍\nme🔥💯😭😂"

    assert selected_text == expected


class _ScrollableSelectApp(App):
    """Test app: 'BEFORE' / scrollable container with 10 items / 'AFTER'."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #before, #after, .item {
        height: 1;
    }
    #scroller {
        height: 5;
        border: none;
        padding: 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("BEFORE", id="before")
        with VerticalScroll(id="scroller"):
            for i in range(10):
                yield Static(f"item-{i:02d}", classes="item", id=f"item-{i}")
        yield Static("AFTER", id="after")


async def test_scroll_and_drag_selection_share_app_input_queue():
    app = _ScrollableSelectApp()
    async with app.run_test(size=(20, 10)) as pilot:
        await pilot.pause()
        scroller = app.query_one("#scroller", VerticalScroll)
        assert await pilot.mouse_down(offset=(1, 1))
        with patch.object(app, "_peek_message", wraps=app._peek_message) as peek:
            # Raw wheel and held-button movement reach the app before being
            # forwarded to the screen. Yield while both pumps have input so the
            # selection observer can inspect the app's next pending event.
            for _ in range(20):
                app.post_message(MouseMove(None, 5, 4, 1, 1, 1, False, False, False))
                app.post_message(MouseScrollDown(None, 5, 4, 0, 1, 0, False, False, False))
                await asyncio.sleep(0)
            await pilot.pause()
            assert await pilot.mouse_up(offset=(5, 4))
            assert peek.call_count > 0
        assert scroller.scroll_y > 0
        assert app.screen.get_selected_text()
        assert app._exception is None


async def test_select_into_scrollable_container():
    """Selecting from outside (above) into a scrollable container should pick up
    items scrolled above the visible area."""

    app = _ScrollableSelectApp()
    async with app.run_test(size=(20, 10)) as pilot:
        await pilot.pause()
        scroller = app.query_one("#scroller", VerticalScroll)
        # Scroll so items 00-02 are scrolled above the visible area.
        scroller.scroll_to(y=3, animate=False)
        await pilot.pause()

        # Selection: start on "BEFORE" (y=0), end inside the container on the
        # last visible row.
        assert await pilot.mouse_down(offset=(0, 0))
        await pilot.pause()
        assert await pilot.mouse_up(offset=(7, 5))
        selected_text = app.screen.get_selected_text() or ""

        assert "BEFORE" in selected_text
        for i in range(0, 7):
            assert (
                f"item-{i:02d}" in selected_text
            ), f"item-{i:02d} missing from {selected_text!r}"
        assert "AFTER" not in selected_text


async def test_select_out_of_scrollable_container():
    """Selecting from inside a scrollable container to outside (below) should
    pick up items scrolled below the visible area."""

    app = _ScrollableSelectApp()
    async with app.run_test(size=(20, 10)) as pilot:
        await pilot.pause()
        # Default scroll: items 05-09 are scrolled below the visible area.
        scroller = app.query_one("#scroller", VerticalScroll)
        assert scroller.scroll_y == 0

        # Selection: start inside the container at top row, end below on "AFTER".
        assert await pilot.mouse_down(offset=(0, 1))
        await pilot.pause()
        assert await pilot.mouse_up(offset=(0, 7))
        selected_text = app.screen.get_selected_text() or ""

        for i in range(0, 10):
            assert (
                f"item-{i:02d}" in selected_text
            ), f"item-{i:02d} missing from {selected_text!r}"
        assert "AFTER" in selected_text
        assert "BEFORE" not in selected_text


async def test_select_across_scrollable_container():
    """Selecting from outside (above) to outside (below) of a scrollable
    container should select all of its content."""

    app = _ScrollableSelectApp()
    async with app.run_test(size=(20, 10)) as pilot:
        await pilot.pause()
        scroller = app.query_one("#scroller", VerticalScroll)
        scroller.scroll_to(y=2, animate=False)
        await pilot.pause()

        # Selection: BEFORE (y=0) to AFTER (y=7).
        assert await pilot.mouse_down(offset=(0, 0))
        await pilot.pause()
        assert await pilot.mouse_up(offset=(0, 7))
        selected_text = app.screen.get_selected_text() or ""

        assert "BEFORE" in selected_text
        assert "AFTER" in selected_text
        for i in range(0, 10):
            assert (
                f"item-{i:02d}" in selected_text
            ), f"item-{i:02d} missing from {selected_text!r}"


async def test_viewport_drag_preserves_native_order_in_long_history():
    class HistoryApp(App):
        CSS = "#history { height: 10; } .item { height: 1; }"

        def compose(self) -> ComposeResult:
            with VerticalScroll(id="history"):
                for index in range(1000):
                    yield Static(f"Record {index:04d}", id=f"record-{index}", classes="item")

    app = HistoryApp()
    async with app.run_test(size=(40, 15)) as pilot:
        history = app.query_one("#history", VerticalScroll)
        history.scroll_to(y=500, animate=False, immediate=True)
        await pilot.pause()
        first = app.query_one("#record-501", Static)
        last = app.query_one("#record-505", Static)
        assert await pilot.mouse_down(first, offset=(0, 0))
        assert await pilot.mouse_up(last, offset=(11, 0))
        state = app.screen._select_state
        assert state is not None and state.end is not None
        accelerated = state._walk_viewport_widgets()
        assert accelerated is not None
        with patch.object(SelectState, "_walk_viewport_widgets", return_value=None):
            assert accelerated == state._walk_selected_widgets()
        text = app.screen.get_selected_text()
        assert text is not None and "Record 0501" in text and "Record 0505" in text
        # The fast path must not truncate an upward drag once its start is
        # scrolled off-screen. The normal walker still owns copy semantics.
        app.screen.clear_selection()
        await pilot.pause()
        baseline_strip = last.render_lines(Region(0, 0, last.size.width, 1))[0]
        assert await pilot.mouse_down(last, offset=(0, 0))
        history.scroll_to(y=480, animate=False, immediate=True)
        await pilot.pause()
        assert not last.region.overlaps(history.content_region)
        earlier = app.query_one("#record-482", Static)
        assert await pilot.mouse_up(earlier, offset=(11, 0))
        offscreen = app.screen._select_state
        assert offscreen is not None and offscreen._walk_viewport_widgets() is None
        selected = app.screen.get_selected_text()
        assert selected is not None and "Record 0482" in selected and "Record 0505" in selected
        history.scroll_to(y=500, animate=False, immediate=True)
        await pilot.pause()
        assert last in app.screen._compositor.visible_widgets
        assert last.render_lines(Region(0, 0, last.size.width, 1))[0] != baseline_strip


async def test_drag_does_not_repaint_unchanged_selected_text():
    class Counted(Static):
        def __init__(self, text: str, **kwargs) -> None:
            super().__init__(text, **kwargs)
            self.selection_updates = 0

        def selection_updated(self, selection) -> None:
            self.selection_updates += 1
            super().selection_updated(selection)

    class HistoryApp(App):
        CSS = "#history { height: 9; } Counted { height: 1; }"

        def compose(self) -> ComposeResult:
            with VerticalScroll(id="history"):
                for index in range(1000):
                    yield Counted(f"Record {index:04d}", id=f"record-{index}")

    app = HistoryApp()
    async with app.run_test(size=(40, 15)) as pilot:
        history = app.query_one("#history", VerticalScroll)
        history.scroll_to(y=500, animate=False, immediate=True)
        await pilot.pause()
        first = app.query_one("#record-501", Counted)
        interior = app.query_one("#record-502", Counted)
        last = app.query_one("#record-504", Counted)
        assert await pilot.mouse_down(first, offset=(0, 0))
        x, y = last.region.x + 2, last.region.y
        await app.screen._forward_event(MouseMove(None, x, y, 2, 1, 1, False, False, False))
        await pilot.pause()
        assert interior in app.screen.selections
        updates = interior.selection_updates
        assert updates == 1
        await app.screen._forward_event(MouseMove(None, x + 1, y, 1, 0, 1, False, False, False))
        await pilot.pause()
        assert interior.selection_updates == updates
        assert last.selection_updates > 1
        assert "Record 0502" in (app.screen.get_selected_text() or "")
        state = app.screen._select_state
        assert state is not None and state.end is not None
        with patch.object(app.screen, "refresh", wraps=app.screen.refresh) as repaint_screen:
            app.screen._select_state = state.update_end(state.screen_offset + (1, 0), state.end)
            await pilot.pause()
            app.screen.clear_selection()
            await pilot.pause()
            repaint_screen.assert_not_called()


class _GappedScrollApp(App):
    """A scrollable container whose items have a 1-row gap between them, so
    moving the mouse across the container crosses non-content rows."""

    CSS = """
    Screen { layout: vertical; }
    #before, #after { height: 1; }
    .item {
        height: 1;
        margin-bottom: 1;
    }
    #scroller {
        height: 7;
        border: none;
        padding: 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("BEFORE", id="before")
        with VerticalScroll(id="scroller"):
            for i in range(8):
                yield Static(f"item-{i:02d}", classes="item", id=f"item-{i}")
        yield Static("AFTER", id="after")


async def test_select_into_scrollable_container_on_gap():
    """Regression: when the end pointer lands on a gap (margin row) inside a
    scrollable container, the selection should extend only to widgets at or
    above that pointer row — not to every widget in the container, which caused
    a flashing selection as the user moved between content widgets."""

    app = _GappedScrollApp()
    async with app.run_test(size=(20, 12)) as pilot:
        await pilot.pause()

        # Layout: BEFORE y=0, scroller y=1..7, items at y=1 (item-0), y=3
        # (item-1), y=5 (item-2), y=7 (item-3). Margin rows y=2, 4, 6.
        # mouse_down on BEFORE, mouse_up at y=2 (gap between item-0 and item-1).
        assert await pilot.mouse_down(offset=(0, 0))
        await pilot.pause()
        assert await pilot.mouse_up(offset=(0, 2))
        selected_text = app.screen.get_selected_text() or ""

        assert "BEFORE" in selected_text
        assert "item-00" in selected_text
        # item-01 onward are below the gap — should NOT be selected.
        for i in range(1, 8):
            assert (
                f"item-{i:02d}" not in selected_text
            ), f"item-{i:02d} should not be in {selected_text!r}"


async def test_select_out_of_scrollable_container_on_gap():
    """Regression: when the start pointer is on a gap (margin row) inside a
    scrollable container and the user drags out below, only widgets at or
    below the pointer row should be selected."""

    app = _GappedScrollApp()
    async with app.run_test(size=(20, 12)) as pilot:
        await pilot.pause()

        # mouse_down at y=2 (gap between item-0 and item-1). mouse_up inside
        # AFTER's text (col 5 of "AFTER" -> just past the last char).
        assert await pilot.mouse_down(offset=(0, 2))
        await pilot.pause()
        assert await pilot.mouse_up(offset=(5, 8))
        selected_text = app.screen.get_selected_text() or ""

        assert "AFTER" in selected_text
        # item-0 is above the start gap row — should NOT be selected.
        assert "item-00" not in selected_text
        # item-01 onward are below the start gap row — should be selected.
        for i in range(1, 8):
            assert (
                f"item-{i:02d}" in selected_text
            ), f"item-{i:02d} missing from {selected_text!r}"


async def test_select_out_of_scroller_skips_earlier_nested_branches():
    """Copy offscreen tail text without visiting unrelated older messages."""
    class Message(VerticalGroup):
        child_queries = 0

        @property
        def displayed_and_visible_children(self):
            self.child_queries += 1
            return super().displayed_and_visible_children

    class HistoryApp(App):
        CSS = "#history { height: 5; } Static { height: 1; }"

        def compose(self) -> ComposeResult:
            with VerticalScroll(id="history"):
                for message in range(100):
                    with Message(id=f"message-{message}"):
                        for row in range(3):
                            yield Static(f"row {message}:{row}", id=f"row-{message}-{row}")
            yield Static("AFTER", id="after")

    app = HistoryApp()
    async with app.run_test(size=(40, 12)) as pilot:
        history = app.query_one("#history", VerticalScroll)
        history.scroll_to(y=285, animate=False, immediate=True)
        await pilot.pause()
        first = app.query_one("#row-95-1")
        after = app.query_one("#after")
        assert await pilot.mouse_down(first, offset=(0, 0))
        messages = list(app.query(Message))
        for message in messages:
            message.child_queries = 0
        assert await pilot.mouse_up(after, offset=(5, 0))
        selected = app.screen.get_selected_text() or ""
        assert selected.splitlines() == [
            f"row {message}:{row}"
            for message in range(95, 100)
            for row in range(3)
            if (message, row) >= (95, 1)
        ] + ["AFTER"]
        assert all(message.child_queries == 0 for message in messages[:95])


async def test_selection_releases_its_geometry_lookup_without_cyclic_gc():
    """A finished drag calculation must not retain its temporary geometry state."""
    app = _ScrollableSelectApp()
    async with app.run_test(size=(20, 10)) as pilot:
        await pilot.pause()
        assert await pilot.mouse_down(offset=(0, 1))
        assert await pilot.mouse_up(offset=(5, 6))
        state = app.screen._select_state
        assert state is not None and state._walk_viewport_widgets() is None

        class GeometryLookup:
            def __init__(self):
                self.original = app.screen.find_widget

            def __call__(self, widget):
                return self.original(widget)

        was_enabled = gc.isenabled()
        gc.disable()
        try:
            lookup = GeometryLookup()
            weak_lookup = ref(lookup)
            with patch.object(app.screen, "find_widget", lookup):
                assert state._walk_selected_widgets()
            del lookup
            assert weak_lookup() is None
        finally:
            if was_enabled:
                gc.enable()


async def test_queued_drag_keeps_events_and_copy_but_coalesces_selection_work():
    class Tracked(Static):
        moves = 0

        def on_mouse_move(self, event: MouseMove):
            self.moves += 1

    class DragApp(App):
        CSS = "#history { height: 8; } Tracked { height: 1; }"
        copy_event = None
        during_drag = None
        after_release = None

        def compose(self) -> ComposeResult:
            with VerticalScroll(id="history"):
                for index in range(100):
                    yield Tracked(f"record {index:03d}", id=f"record-{index}")

        async def on_event(self, event):
            result = await super().on_event(event)
            if event is self.copy_event:
                # Copy in the middle of a queued burst must see this position,
                # rather than the last computed selection or a future one.
                self.during_drag = self.screen.get_selected_text()
            return result

        def on_text_selected(self):
            self.after_release = self.screen.get_selected_text()

    app = DragApp()
    async with app.run_test(size=(40, 12)) as pilot:
        history = app.query_one("#history", VerticalScroll)
        history.scroll_to(y=90, animate=False, immediate=True)
        await pilot.pause()
        first = app.query_one("#record-92")
        last = app.query_one("#record-94", Tracked)
        assert await pilot.mouse_down(first, offset=(0, 0))
        moves = [MouseMove(None, last.region.x + 2 + index % 5, last.region.y,
                           1, 0, 1, False, False, False) for index in range(79)]
        moves.append(MouseMove(None, last.region.x + 10, last.region.y,
                               1, 0, 1, False, False, False))
        app.copy_event = moves[10]
        before_moves = last.moves
        with patch.object(app.screen, "_apply_selection_state", wraps=app.screen._apply_selection_state) as apply:
            for event in moves:
                app.post_message(event)
            app.post_message(MouseUp(None, last.region.x + 10, last.region.y,
                                     0, 0, 1, False, False, False))
            await pilot.pause()
            assert apply.call_count < len(moves) // 4
        assert last.moves - before_moves == len(moves)
        assert app.during_drag == "record 092\nrecord 093\nre"
        assert app.after_release == "record 092\nrecord 093\nrecord 094"
        assert app.screen.get_selected_text() == app.after_release
        assert not app.screen._selection_update_pending

        # A clear during deferred work must not resurrect the old selection.
        state = app.screen._select_state
        assert state is not None and state.end is not None
        app.post_message(MouseMove(None, last.region.x + 4, last.region.y,
                                   1, 0, 1, False, False, False))
        app.screen._select_state = state.update_end(state.screen_offset + (1, 0), state.end)
        assert app.screen._selection_update_pending
        app.screen.clear_selection()
        await pilot.pause()
        assert app.screen.get_selected_text() is None
        assert not app.screen._selection_update_pending
