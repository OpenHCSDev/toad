"""Textual-facing: sidebar arrow buttons follow spatial neighbours (walls, inward swaps, outward swaps, cross-centre moves) as laid out by the compositor."""

from toad.widgets.side_bar import SideBar, SidebarAction


def arrows(bar: SideBar) -> list[str]:
    return [button.render().plain for button in bar.query(SidebarAction)
            if button.display and button.action.directional]


async def test_arrow_clicks_follow_spatial_neighbours(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        channels = app.screen.query_one("#channels-sidebar", SideBar)
        thread = app.selected_session.query_one("#thread-sidebar", SideBar)
        thread.reveal()
        await ui.step()

        async def click(bar: SideBar, label: str) -> None:
            button = next(button for button in bar.query(SidebarAction)
                          if button.display and button.render().plain == label)
            assert await pilot.click(button), (
                bar.id, label, button.region, bar.region,
                tuple((item.id, item.region, item.collapsed) for item in app.screen.query(SideBar)),
                button in app.screen._compositor.visible_widgets)
            await ui.step()

        assert arrows(channels) == ["──>"] and arrows(thread) == ["<──"], (
            arrows(channels), arrows(thread), ui.visible_text())
        await click(thread, "<──")
        assert not channels.right and not thread.right
        assert channels.region.right == thread.region.x
        assert arrows(channels) == ["──>"], "Wall-adjacent bar must have only the inward arrow"
        assert arrows(thread) == ["<──", "──>"]

        await click(channels, "──>")
        assert not channels.right and not thread.right, "Inward click must swap, not cross the conversation"
        assert thread.region.right == channels.region.x
        assert arrows(thread) == ["──>"] and arrows(channels) == ["<──", "──>"]
        await click(channels, "<──")
        assert channels.region.right == thread.region.x
        await click(thread, "──>")
        assert thread.right and not channels.right

        await click(channels, "──>")
        assert channels.right and thread.right
        assert channels.region.right == thread.region.x
        assert arrows(thread) == ["<──"] and arrows(channels) == ["<──", "──>"]
        await click(thread, "<──")
        assert channels.right and thread.right
        assert thread.region.right == channels.region.x
        assert arrows(channels) == ["<──"] and arrows(thread) == ["<──", "──>"]
        await click(thread, "──>")
        assert channels.region.right == thread.region.x

        # Float and a collapsed neighbour do not change the arrow policy.
        await click(thread, "Float")
        channels.toggle()
        await ui.step()
        assert arrows(thread) == ["<──"]
        await click(thread, "<──")
        assert thread.right and channels.right
        assert thread.region.right == channels.region.x
        assert arrows(thread) == ["<──", "──>"]
        channels.reveal()
        await ui.step()
        assert arrows(channels) == ["<──"]
