"""Textual-facing: pointer capture, drag, hover styling and keyboard resize of a sidebar from either edge, with the width slider mirrored."""

import pytest

from toad.core import events as core_events
from toad.widgets.side_bar import (
    SideBar, SideBarToggle, SidebarAction, SidebarResizeHandle, SidebarSlider, TabHistoryControls,
)


@pytest.mark.parametrize("side", ["left", "right"])
async def test_resize_by_edge_drag_slider_and_keys_follows_the_side(workspace, side):
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        bar = app.screen.query_one("#channels-sidebar", SideBar)
        app.sidebar_layout.move("channels-sidebar", side)
        app.sidebar_layout.width("channels-sidebar", 30)
        app.events.publish(core_events.SidebarLayoutChanged())
        await ui.step()
        slider = bar.query_one("#sidebar-width-slider", SidebarSlider)
        handle = bar.query_one(SidebarResizeHandle)
        toggle = bar.query_one(SideBarToggle)
        assert (toggle.region.right == handle.region.x if side == "left"
                else toggle.region.x == handle.region.right), (side, toggle.region, handle.region)
        direction = 1 if side == "left" else -1
        assert slider.reversed == (side == "right")
        for theme in ("ansi-dark", "textual-dark"):
            app.theme = theme
            ui.conversation.prompt.focus()
            await pilot.hover(app.screen.query_one(TabHistoryControls))
            await ui.step()
            normal = handle.styles.color
            assert await pilot.hover(handle, offset=(0, 3))
            await ui.step()
            assert handle.styles.color != normal and "hover" in handle.pseudo_classes
            for selector in (f"#sidebar-{'right' if side == 'left' else 'left'}", "#sidebar-float"):
                button = bar.query_one(selector, SidebarAction)
                normal = button.styles.background
                assert await pilot.hover(button)
                await ui.step()
                assert button.styles.background != normal
                await pilot.hover(handle, offset=(0, 3))
        start = handle.region.x
        y = handle.region.y + 3
        old_width = bar.size.width
        assert await pilot.mouse_down(handle, offset=(0, 3))
        assert not app.screen._selecting, "Resize handle started a text selection"
        await pilot.hover(offset=(start + direction * 12, y))
        assert not app.screen._selecting, "Resize drag traversed selectable content"
        await pilot.mouse_up(offset=(start + direction * 12, y))
        await ui.step()
        assert bar.size.width == old_width + 12, (side, bar.size, old_width)
        assert slider.value == app.sidebar_layout.get(bar.id).width_percent == 40
        assert not handle._dragging and app.mouse_captured is None

        # The physical arrow keys and slider endpoints mirror as well.
        slider.focus()
        await ui.press("right" if side == "left" else "left")
        assert slider.value == 41
        await ui.press("left" if side == "left" else "right")
        assert slider.value == 40
        inward = slider.size.width - 1 if side == "left" else 0
        assert await pilot.mouse_down(slider, offset=(inward, 0))
        assert not app.screen._selecting, "Width slider started a text selection"
        assert await pilot.mouse_up(slider, offset=(inward, 0))
        await ui.step()
        assert slider.value == 50 and bar.size.width == 60, (side, slider.value, bar.region)
        outward = 4 if side == "left" else slider.size.width - 1
        # Width changes on press, then the capture owner gets the release.
        # A final Click may land outside the track it has just resized.
        assert await pilot.mouse_down(slider, offset=(outward, 0))
        await pilot.mouse_up(offset=(slider._drag_origin_x + outward, slider.region.y))
        await ui.step()
        assert slider.value == 15 and bar.size.width == 18
        assert handle.region.x == (bar.region.right - 1 if side == "left" else bar.region.x)
        bar.toggle()
        await ui.step()
        assert not handle.display
        assert toggle.region == bar.region
        bar.reveal()
        await ui.step()
        assert handle.display
