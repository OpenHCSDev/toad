"""Actual native layout for horizontally scrolling sidebar headers."""

import asyncio
import json

from textual.app import App, ComposeResult
from textual.containers import VerticalGroup
from textual.widgets import Button, Static

from toad.widgets.sidebar_viewport import SidebarHeader, SidebarViewport


class HeaderApp(App):
    CSS = """
    SidebarViewport { width: 1fr; height: 1fr; scrollbar-gutter: stable; }
    VerticalGroup { width: auto; height: auto; }
    SidebarHeader { height: 1; }
    SidebarHeader > Static { width: 1fr; height: 1; }
    SidebarHeader > Button { width: 6; min-width: 6; height: 1; border: none; }
    .wide { width: 120; height: 30; }
    """

    def compose(self) -> ComposeResult:
        with SidebarViewport():
            for index in range(2):
                with VerticalGroup():
                    with SidebarHeader():
                        yield Static(f"Header {index}")
                        yield Button("Menu")
                    yield Static("wide scrolling content", classes="wide")


def verify(app):
    viewport = app.query_one(SidebarViewport)
    container = viewport.region.shrink(viewport.styles.gutter)
    child_region = (container if viewport.loading
                    else viewport._get_scrollable_region(container))
    for header in viewport.query(SidebarHeader):
        assert header.region.width == child_region.width, (header.region, child_region)
        assert header.region.x == child_region.x, (header.region, child_region)
        assert header.styles.offset.x.value == int(viewport.scroll_x)
    return {"viewport": child_region.width, "scroll_x": viewport.scroll_x,
            "headers": [header.region.width for header in viewport.query(SidebarHeader)]}


async def main():
    app = HeaderApp()
    observations = []
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        observations.append(verify(app))
        viewport = app.query_one(SidebarViewport)
        viewport.scroll_to(x=12, animate=False, immediate=True, force=True)
        await pilot.pause()
        observations.append(verify(app))
        for width in (61, 93, 47):
            await pilot.resize_terminal(width, 30)
            await pilot.pause()
            observations.append(verify(app))
        viewport.loading = True
        await pilot.pause()
        # Loading owns a native cover; parked headers have no visible boxes.
        visible = app.screen._compositor.visible_widgets
        assert viewport._cover_widget in visible
        assert all(header not in visible for header in viewport.query(SidebarHeader))
        viewport.loading = False
        await pilot.pause()
        observations.append(verify(app))
    print(json.dumps({"observations": observations, "loading_restored": True}))


if __name__ == "__main__":
    asyncio.run(main())
