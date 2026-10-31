"""Native sidebar controls reflect the placement owner at every declared edge."""

import pytest

from toad.sidebar_layout import SidebarEdge
from toad.widgets.side_bar import SideBar, SidebarAction


@pytest.mark.parametrize("side", SidebarEdge.members_with(SidebarEdge))
async def test_arrow_clicks_follow_spatial_neighbours(workspace, side):
    async with workspace.app(size=(120, 60)) as ui:
        app, pilot = ui.textual
        channels = app.screen.query_one("#channels-sidebar", SideBar)
        thread = app.selected_session.query_one("#thread-sidebar", SideBar)
        channels.reveal()
        thread.reveal()
        app.sidebar_layout.move(channels.id, side)
        app.sidebar_layout.move(thread.id, side)
        app.workspace_chrome.refresh_layout()
        await ui.step()

        async def click(bar: SideBar, edge) -> None:
            button = bar.query_one(f"#sidebar-{edge.declared_name}", SidebarAction)
            assert button.display and await pilot.click(button), (bar.id, edge, button.region, bar.region)
            await ui.step()

        def check_controls(bar: SideBar) -> None:
            for edge, shift in app.sidebar_layout.directions(bar.id).items():
                button = bar.query_one(f"#sidebar-{edge.declared_name}", SidebarAction)
                assert button.display == shift.available

        def check_adjacent() -> None:
            regions = sorted((channels.region, thread.region), key=lambda region: side.coordinate(region.offset))
            assert side.coordinate(regions[0].offset) + side.extent(regions[0].size) == side.coordinate(regions[1].offset)

        # The wall is blocked, the inward arrow swaps, then crosses the centre.
        assert channels.placement.order == 0 and thread.placement.order == 1
        check_controls(channels)
        check_controls(thread)
        check_adjacent()
        inward = side.opposite()
        await click(channels, inward)
        assert channels.placement.side is thread.placement.side is side
        assert thread.placement.order == 0 and channels.placement.order == 1
        check_adjacent()
        await click(channels, side)
        assert channels.placement.order == 0 and thread.placement.order == 1
        await click(thread, inward)
        assert thread.placement.side is inward and channels.placement.side is side
        await click(channels, inward)
        assert channels.placement.side is thread.placement.side is inward
        check_controls(channels)
        check_controls(thread)
        check_adjacent()

        # Float and collapse keep the same canonical peer/action policy.
        assert await pilot.click(thread.query_one("#sidebar-float", SidebarAction))
        channels.toggle(focus=False)
        await ui.step()
        check_controls(thread)
        await click(thread, side)
        assert thread.placement.side is channels.placement.side is inward
        channels.reveal()
        await ui.step()
        check_controls(channels)
        check_controls(thread)
