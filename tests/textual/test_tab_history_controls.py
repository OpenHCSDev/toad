"""Textual-facing: the Back, Forward and menu buttons' place in the header, their size, their paint and hover styles."""

from toad.widgets.side_bar import ThreadSidebar
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.workspace_chrome import WorkspaceHeader
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import BackTabButton, ForwardTabButton, TabHistoryControls


def arrow_style(screen, button):
    row = screen._compositor.render_strips()[button.region.y + 1]
    return next(iter(row.crop(button.region.x + 2, button.region.x + 3))).style


async def test_unavailable_buttons_sit_in_the_header_and_ignore_hover(workspace):
    async with workspace.app(size=(100, 36)) as ui:
        app, pilot = ui.textual
        screen = app.screen
        first = ui.selected_tab
        left = screen.query_one(ChannelsSidebar)
        controls = screen.query_one(TabHistoryControls)
        header = screen.query_one(WorkspaceHeader)
        assert controls.parent is header
        assert screen.query_one(SessionsTabs).parent is header
        assert controls.region.y == screen.query_one(SessionsTabs).region.y == 0
        back = controls.query_one(BackTabButton)
        assert back.region.width == 7 and back.region.height == 3
        assert controls.region.height == 3
        assert back.disabled
        assert controls.query_one(ForwardTabButton).disabled
        assert back.tooltip == "No earlier visited tab"
        unavailable_style = arrow_style(screen, back)
        await pilot.hover(back)
        await ui.step()
        assert arrow_style(screen, back) == unavailable_style
        assert await pilot.click(back)
        assert ui.selected_tab == first
        assert not screen.query_one(ThreadSidebar).query(TabHistoryControls)
        assert controls.region.y < left.region.y
        assert controls.region.y < left.query_one("CollapsibleTitle").region.y
        left.collapsed = True
        await ui.step()
        assert controls.display and controls in screen._compositor.visible_widgets
        left.collapsed = False
        await ui.step()
        assert controls.display


async def test_available_back_button_paints_its_arrow_and_hover_style(workspace):
    workspace.thread("owner")
    async with workspace.app(size=(100, 36)) as ui:
        app, pilot = ui.textual
        channel = await ui.open_channel("#all", actor="owner")
        assert ui.selected_tab == channel
        screen = app.screen
        assert screen.query_one(SessionsTabs).display
        assert screen.query_one(SessionsTabs).region.y == 0
        assert not screen.query_one(BackTabButton).disabled
        assert screen.query_one(ForwardTabButton).disabled
        back = screen.query_one(BackTabButton)
        painted = [strip.text for strip in screen._compositor.render_strips()]
        assert "<──" in painted[back.region.y + 1]
        assert "<──" not in painted[back.region.y]
        await pilot.hover(screen.query_one("CollapsibleTitle"))
        await ui.step()
        painted_before = arrow_style(screen, back)
        await pilot.hover(back)
        await ui.step()
        painted_after = arrow_style(screen, back)
        assert painted_after != painted_before
        assert painted_after.bgcolor != painted_before.bgcolor
        sidebar = screen.query_one(ChannelsSidebar)
        sidebar.collapsed = True
        await ui.step()
        assert screen.query_one(TabHistoryControls) in screen._compositor.visible_widgets


async def test_preview_tab_keeps_the_controls_in_the_header_and_clickable(workspace):
    async with workspace.app(size=(100, 36)) as ui:
        app, pilot = ui.textual
        path = workspace.project / "readme.md"
        path.write_text("# Preview stays navigable\n")
        await ui.open_preview(path)
        screen = app.screen
        assert screen.query_one(TabHistoryControls).region.y == screen.query_one(SessionsTabs).region.y == 0
        back = screen.query_one(BackTabButton)
        assert await pilot.click(BackTabButton), (
            back.region, back.display, back in screen._compositor.visible_widgets, back.disabled)
