"""Textual-facing: applying sidebar intent consumes the committed parent extent and leaves dirty full geometry to the native layout."""

from toad.widgets.side_bar import ThreadSidebar
from toad.widgets.channels_sidebar import ChannelsSidebar
from unittest.mock import patch

from toad.widgets.side_bar import SideBar


async def test_toggling_a_sidebar_does_not_reflow_dirty_geometry_synchronously(workspace):
    async with workspace.app(size=(130, 43)) as ui:
        app, _ = ui.textual
        compositor = app.screen._compositor
        for sidebar in (app.screen.query_one(ChannelsSidebar), app.selected_session.query_one(ThreadSidebar)):
            for _ in range(2):
                compositor._full_map_invalidated = True
                compositor._visible_map = None
                with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
                    sidebar.toggle(focus=False)
                assert arrange.call_count == 0, "Sidebar intent performed a synchronous full reflow"
                await ui.step()
