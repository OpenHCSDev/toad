"""Group headers paint in ordinary flow, without a sidebar scrollport lifetime."""

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from toad.textual_colours import ThemedApp
from toad.widgets.comms_sidebar import ChannelHeader
from toad.widgets.sidebar_viewport import SidebarHeader


class GroupHeaderApp(ThemedApp, App):
    CSS = "SidebarHeader { height: 1; } SidebarHeader > Static { height: 1; }"

    def __init__(self, header: SidebarHeader) -> None:
        super().__init__()
        self.header = header

    def compose(self) -> ComposeResult:
        yield self.header


@pytest.mark.parametrize("header_type", (SidebarHeader, ChannelHeader))
async def test_group_header_paints_without_a_sidebar_viewport(
    header_type: type[SidebarHeader],
):
    label = Static("Channel group")
    header = header_type(label, classes="group-header")
    app = GroupHeaderApp(header)
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        assert header in app.screen._compositor.visible_widgets
        assert label in app.screen._compositor.visible_widgets
        assert header.region.width == app.screen.content_region.width
        assert label.region.height == 1
