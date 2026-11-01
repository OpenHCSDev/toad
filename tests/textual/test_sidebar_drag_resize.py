"""Textual-facing: captured resize, hover and keys; zero-motion release preserves intent on every edge."""

import pytest

from toad.key_modes import Standard
from toad.keymap import KeymapRow
from toad.preferences import SETTINGS
from textual.keys import RightKey
from toad.sidebar_layout import SidebarEdge, WidthSidebarEdge
from toad.widgets.side_bar import (
    SideBar, SideBarToggle, SidebarAction, SidebarResizeHandle, SidebarSlider, TabHistoryControls,
)


@pytest.mark.parametrize("side", SidebarEdge.members_with(WidthSidebarEdge))
async def test_resize_by_edge_drag_slider_and_keys_follows_the_side(workspace, side):
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        bar = app.screen.query_one("#channels-sidebar", SideBar)
        app.sidebar_layout.move("channels-sidebar", side)
        app.sidebar_layout.resize("channels-sidebar", 30)
        app.workspace_chrome.refresh_layout()
        await ui.step()
        slider = bar.extent_slider
        handle = bar.query_one(SidebarResizeHandle)
        toggle = bar.query_one(SideBarToggle)
        assert (toggle.region.right == handle.region.x if side.sign > 0
                else toggle.region.x == handle.region.right), (side, toggle.region, handle.region)
        direction = side.sign
        assert slider.reversed == (side.sign < 0)
        for theme in ("ansi-dark", "textual-dark"):
            app.theme = theme
            ui.conversation.prompt.focus()
            await pilot.hover(app.screen.query_one(TabHistoryControls))
            await ui.step()
            normal = handle._paint_state.foreground
            assert await pilot.hover(handle, offset=(0, 3))
            await ui.step()
            assert handle._paint_state.foreground != normal and "hover" in handle.pseudo_classes
            for selector in (f"#sidebar-{side.opposite().declared_name}", "#sidebar-float"):
                button = bar.query_one(selector, SidebarAction)
                normal = button._paint_state.background
                assert await pilot.hover(button)
                await ui.step()
                assert button._paint_state.background != normal
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
        assert slider.value == app.sidebar_layout.get(bar.id).extent_percent == 40
        assert not handle._dragging and app.mouse_captured is None

        # The physical arrow keys and slider endpoints mirror as well.
        slider.focus()
        await ui.press("right" if side.sign > 0 else "left")
        assert slider.value == 41
        await ui.press("left" if side.sign > 0 else "right")
        assert slider.value == 40
        remapped_key = "ctrl+f6"  # Plain f6 already belongs to TextArea's Select line.
        remap = app.settings.ui.keymap.changed(KeymapRow.of(RightKey(), Standard), (remapped_key,))
        app.saved_settings.set(SETTINGS.ui.keymap.bindings, remap.bindings)
        for control in (slider, handle):
            control.focus()
            await ui.press("right")
            assert slider.value == 40
            await ui.press(remapped_key)
            assert slider.value == 40 + direction
            await ui.press("left")
            assert slider.value == 40
        inward = slider.size.width - 1 if side.sign > 0 else 0
        assert await pilot.mouse_down(slider, offset=(inward, 0))
        assert not app.screen._selecting, "Width slider started a text selection"
        assert await pilot.mouse_up(slider, offset=(inward, 0))
        await ui.step()
        assert slider.value == 50 and bar.size.width == 60, (side, slider.value, bar.region)
        outward = 4 if side.sign > 0 else slider.size.width - 1
        # Width changes on press, then the capture owner gets the release.
        # A final Click may land outside the track it has just resized.
        assert await pilot.mouse_down(slider, offset=(outward, 0))
        await pilot.mouse_up(offset=(slider._drag_origin_x + outward, slider.region.y))
        await ui.step()
        assert slider.value == 15 and bar.size.width == 18
        assert handle.region.x == (bar.region.right - 1 if side.sign > 0 else bar.region.x)
        bar.toggle()
        await ui.step()
        assert not handle.display
        assert toggle.region == bar.region
        bar.reveal()
        await ui.step()
        assert handle.display


@pytest.mark.parametrize("side", SidebarEdge.members_with(SidebarEdge))
async def test_zero_motion_resize_keeps_requested_percentage_on_every_edge(workspace, side):
    async with workspace.app(size=(51, 27)) as ui:
        app, pilot = ui.textual
        bar = app.screen.query_one("#channels-sidebar", SideBar)
        app.sidebar_layout.move(bar.id, side)
        app.sidebar_layout.resize(bar.id, 40)
        bar.reveal()
        app.workspace_chrome.refresh_layout()
        await ui.step()
        handle = bar.query_one(SidebarResizeHandle)
        before = bar.region
        assert await pilot.click(handle)
        await ui.step()
        assert bar.placement.extent_percent == 40
        assert bar.region == before
        assert not handle._dragging and app.mouse_captured is None
