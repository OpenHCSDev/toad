import gc
from unittest.mock import patch
from weakref import ref

from textual._compositor import Compositor
from textual.app import App
from textual.content import Content
from textual.geometry import Size
from textual.screen import Screen
from textual.widget import Widget


def test_cleared_compositor_releases_root_and_cannot_rebuild_the_old_scene():
    compositor = Compositor()
    widget = Widget()
    weak_widget = ref(widget)
    compositor.root = widget
    compositor.size = Size(80, 24)
    compositor.widgets.add(widget)
    compositor.clear()
    del widget
    gc.collect()
    assert weak_widget() is None, "Cleared compositor still owns its root"
    with patch.object(compositor, "_arrange_root", side_effect=AssertionError("Closed scene rebuilt")):
        assert not compositor.full_map


async def test_removed_widget_releases_derived_visual_while_the_widget_is_retained():
    class Rendered(Widget):
        def render(self):
            return Content("derived text " * 100)

    app = App()
    async with app.run_test() as pilot:
        widget = Rendered()
        await app.mount(widget)
        await pilot.pause()
        visual = ref(widget._render())
        await widget.remove()
        await pilot.pause()
        gc.collect()
        assert visual() is None, "Closed widget retained its derived render content"
        assert not widget._styles_cache._cache


async def test_closed_screen_drops_pending_presentation_callbacks():
    app = App()
    async with app.run_test() as pilot:
        screen = Screen()
        await app.push_screen(screen)
        await pilot.pause()
        # A suspended screen has no future painted frame on which to deliver
        # presentation callbacks. Closing it must release their owners.
        await app.pop_screen()
        await pilot.pause()
        assert screen._compositor.root is None
        assert not screen._callbacks and not screen._layout_widgets
