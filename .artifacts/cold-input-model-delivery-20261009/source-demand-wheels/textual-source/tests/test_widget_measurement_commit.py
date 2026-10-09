from unittest.mock import patch

import pytest

from textual.app import App
from textual.containers import VerticalScroll
from textual.geometry import Size
from textual.widget import Widget
from textual.widgets import Static


class Measured(Widget):
    DEFAULT_CSS = "Measured { width: 10; height: 4; overflow: hidden hidden; }"

    def __init__(self, *children):
        self.observed = []
        self.resize_from_watch = False
        super().__init__(*children)

    def watch_virtual_size(self, value):
        self.observed.append(value)
        if self.resize_from_watch:
            self.styles.height = value.height


@pytest.mark.parametrize("widget_type", [Measured, VerticalScroll])
async def test_content_derived_extent_keeps_scrollbar_and_authored_invalidation(widget_type):
    app = App()
    async with app.run_test() as pilot:
        widget = widget_type(Static("child"))
        widget.styles.width = 10
        widget.styles.height = 4
        widget.styles.overflow_y = "auto"
        await app.mount(widget)
        await pilot.pause()
        with patch.object(widget, "refresh", wraps=widget.refresh) as refresh:
            widget._size_updated(Size(10, 4), Size(10, 12), Size(10, 4))
            assert widget.show_vertical_scrollbar
            assert any(call.kwargs.get("layout") for call in refresh.call_args_list)
            refresh.reset_mock()
            widget._size_updated(Size(10, 4), Size(10, 16), Size(10, 4))
            assert widget.virtual_size == Size(10, 16)
            assert not any(call.kwargs.get("layout") for call in refresh.call_args_list)
            widget.virtual_size = Size(10, 20)
            assert any(call.kwargs.get("layout") for call in refresh.call_args_list)
            if isinstance(widget, Measured):
                refresh.reset_mock()
                widget.resize_from_watch = True
                widget._size_updated(Size(10, 4), Size(10, 24), Size(10, 4))
                assert widget.styles.height.value == 24
                assert any(call.kwargs.get("layout") for call in refresh.call_args_list)


async def test_scroll_container_resize_and_content_changes_keep_native_geometry():
    app = App()
    async with app.run_test(size=(40, 12)) as pilot:
        content = Static("wide text " * 60)
        window = VerticalScroll(content)
        await app.mount(window)
        await pilot.pause()
        assert window.show_vertical_scrollbar
        window.scroll_end(animate=False)
        await pilot.pause()
        assert window.scroll_y == window.max_scroll_y > 0
        content.update("short")
        await pilot.pause()
        assert not window.show_vertical_scrollbar
        assert window.scroll_y == window.max_scroll_y == 0
        await pilot.resize_terminal(20, 8)
        content.update("narrow text " * 40)
        await pilot.pause()
        assert window.show_vertical_scrollbar
        assert content.size.width == window.content_size.width - window.scrollbar_size_vertical
        assert window.virtual_size.height >= content.size.height > window.content_size.height


async def test_custom_extent_input_can_retain_layout_feedback():
    class ExtentInput(Measured):
        def _measured_virtual_size_requires_layout(self):
            return True

    app = App()
    async with app.run_test() as pilot:
        widget = ExtentInput(Static("child"))
        await app.mount(widget)
        await pilot.pause()
        with patch.object(widget, "refresh", wraps=widget.refresh) as refresh:
            widget._size_updated(Size(10, 4), Size(10, 12), Size(10, 4))
            assert any(call.kwargs.get("layout") for call in refresh.call_args_list)


async def test_committed_extent_notifies_watchers_without_remeasuring_parent():
    app = App()
    async with app.run_test() as pilot:
        widget = Measured()
        await app.mount(widget)
        await pilot.pause()
        with patch.object(widget, "refresh", wraps=widget.refresh) as refresh:
            widget._size_updated(Size(10, 4), Size(10, 12), Size(10, 4))
            assert widget.observed[-1] == Size(10, 12)
            assert not any(call.kwargs.get("layout") for call in refresh.call_args_list)
            # Authored extent changes remain ordinary layout inputs.
            widget.virtual_size = Size(10, 16)
            assert any(call.kwargs.get("layout") for call in refresh.call_args_list)


async def test_extent_watcher_can_still_request_real_geometry_change():
    app = App()
    async with app.run_test() as pilot:
        widget = Measured()
        await app.mount(widget)
        await pilot.pause()
        widget.resize_from_watch = True
        with patch.object(widget, "refresh", wraps=widget.refresh) as refresh:
            widget._size_updated(Size(10, 4), Size(10, 8), Size(10, 4))
            assert widget.styles.height.value == 8
            assert any(call.kwargs.get("layout") for call in refresh.call_args_list)


async def test_committed_extent_keeps_scrollbar_layout_invalidation():
    app = App()
    async with app.run_test() as pilot:
        widget = Measured(Widget())
        widget.styles.overflow_y = "auto"
        await app.mount(widget)
        await pilot.pause()
        assert not widget.show_vertical_scrollbar
        with patch.object(widget, "refresh", wraps=widget.refresh) as refresh:
            widget._size_updated(Size(10, 4), Size(10, 20), Size(10, 4))
            assert widget.show_vertical_scrollbar
            assert any(call.kwargs.get("layout") for call in refresh.call_args_list)


async def test_unchanged_geometry_retains_visual_until_content_refresh():
    app = App()
    async with app.run_test() as pilot:
        widget = Static("original")
        await app.mount(widget)
        await pilot.pause()
        visual = widget._render()
        with patch.object(widget, "render", wraps=widget.render) as render:
            widget._size_updated(widget._size, widget.virtual_size, widget._container_size)
            assert widget._render() is visual
            render.assert_not_called()
            widget.update("changed")
            assert widget._render() is not visual
            assert render.call_count == 1


async def test_dirty_mark_does_not_materialize_invalidated_compositor():
    app = App()
    async with app.run_test() as pilot:
        widget = Static("original")
        await app.mount(widget)
        await pilot.pause()
        compositor = app.screen._compositor
        compositor._full_map_invalidated = True
        with patch.object(compositor, "_arrange_root", side_effect=AssertionError("Invalidation performed layout")):
            widget.refresh(layout=True)
            widget._size_updated(Size(35, 5), Size(35, 5), Size(35, 5))
        assert widget._size.region in widget._dirty_regions


async def test_non_scrolling_group_commits_extent_without_remeasuring_ancestors():
    app = App()
    async with app.run_test() as pilot:
        group = Measured(Static("child"))
        await app.mount(group)
        await pilot.pause()
        with patch.object(group, "refresh", wraps=group.refresh) as refresh:
            group._size_updated(Size(10, 4), Size(10, 30), Size(10, 4))
            assert group.observed[-1] == Size(10, 30)
            assert not any(call.kwargs.get("layout") for call in refresh.call_args_list)
            group.virtual_size = Size(10, 40)
            assert any(call.kwargs.get("layout") for call in refresh.call_args_list)
