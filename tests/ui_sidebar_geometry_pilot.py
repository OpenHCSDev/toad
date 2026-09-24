"""Screenshot regressions: full-width header and edge-bound sidebar geometry."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from textual.containers import VerticalScroll

from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.virtual_channel_list import VirtualChannelList
from toad.widgets.side_bar import SideBar, SidebarAction, SidebarResizeHandle, SideBarToggle, TabHistoryControls


async def main() -> None:
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    with tempfile.TemporaryDirectory(prefix="toad-ui-sidebar-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        comms = wire(root / "wire")
        for index in range(35):
            comms.register(Thread(f"worker-{index:02}-" + "long-name-" * 5,
                                  frozenset(), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.screen.query_one(CommsSidebar).sync_sessions()
            await pilot.pause()
            left = app.screen.query_one("#channels-sidebar", SideBar)
            right = app.screen.query_one("#thread-sidebar", SideBar)
            controls = app.screen.query_one(TabHistoryControls)
            tabs = app.screen.query_one(SessionsTabs)
            check(controls.region.x == 0, "header controls must start at screen left")
            check(tabs.region.x == controls.region.right and tabs.region.right == 120,
                  "tabs must follow controls and fill the rest of the header")
            check(not left.query("#sidebar-horizontal-slider"), "duplicate horizontal slider")
            for percentage in (50, 30, 15):
                app.sidebar_layout.width("channels-sidebar", percentage)
                app.sidebar_layout_changed.publish(None)
                await pilot.pause()
                scrolls = [node for node in left.walk_children()
                           if node.show_vertical_scrollbar and node.scrollbar_size_vertical > 0
                           and node.display]
                check(bool(scrolls), "long roster needs a vertical scrollbar")
                for node in scrolls:
                    check(node.vertical_scrollbar.region.right <= left.region.right,
                          f"vertical scrollbar clipped at width {percentage}%")
                    check(node.vertical_scrollbar.region.right == node.region.right,
                          "vertical scrollbar must remain on the viewport's right edge")
            panels = left.query_one("#sidebar-panels", VerticalScroll)
            check(panels.show_horizontal_scrollbar, "long rows need native horizontal scrolling")
            listing = left.query_one_optional(VirtualChannelList)
            if listing is not None:
                listing.action_last()
                await pilot.pause()
                check(panels.scroll_y > 0, "virtual keyboard navigation must scroll the sidebar")
            for selector in ("#sidebar-move", "#sidebar-float"):
                button = left.query_one(selector, SidebarAction)
                app.screen.conversation.prompt.focus()
                await pilot.hover(app.screen.query_one(TabHistoryControls))
                await pilot.pause()
                normal = button.styles.background
                await pilot.hover(button)
                await pilot.pause()
                check("hover" in button.pseudo_classes and button.styles.background != normal,
                      f"{selector} hover needs a visible background change")
            app.sidebar_layout.move("thread-sidebar", "left")
            right.reveal()
            app.sidebar_layout_changed.publish(None)
            await pilot.pause()
            before = (left.region, right.region)
            app.sidebar_layout.float_mode("thread-sidebar")
            app.sidebar_layout_changed.publish(None)
            await pilot.pause()
            check((left.region, right.region) == before, "Float must not move/resize either bar")
            left.toggle()
            await pilot.pause()
            check(right.region.x == left.region.right,
                  "floating peer must pack against the collapsed outer bar")
            app.sidebar_layout.float_mode("thread-sidebar")
            app.sidebar_layout_changed.publish(None)
            await pilot.pause()
            check(right.region.x == left.region.right, "Push must use the same packed position")
            for side in ("left", "right"):
                left.reveal()
                right.reveal()
                app.sidebar_layout.move("channels-sidebar", side)
                app.sidebar_layout.move("thread-sidebar", side)
                app.sidebar_layout_changed.publish(None)
                await pilot.pause()

                def packed() -> None:
                    outer, inner = sorted((left, right), key=lambda bar: bar.region.x)
                    check(outer.region.right == inner.region.x, f"{side} sidebar packing gap")
                    for item in (left, right):
                        edge = item.query_one(SideBarToggle if item.collapsed else SidebarResizeHandle)
                        check(app.get_widget_at(edge.region.x, edge.region.y + 3)[0] is edge,
                              "sidebar edge must remain above the conversation and clickable")

                packed()
                for bar in (left, right):
                    before = (left.region, right.region)
                    order = app.sidebar_layout.ordered()
                    bar.query_one("#sidebar-float", SidebarAction).action_activate()
                    await pilot.pause()
                    check((left.region, right.region) == before, f"{side} Float moved bars")
                    check(app.sidebar_layout.ordered() == order, "Float reordered bars")
                    content = app.screen.query_one("#session-content")
                    pushing = [item for item in (left, right)
                               if not app.sidebar_layout.get(item.id).floating]
                    if side == "left":
                        check(content.region.x == max((item.region.right for item in pushing), default=0),
                              "left pushed extent must match conversation start")
                    else:
                        check(content.region.right == min((item.region.x for item in pushing), default=120),
                              "right pushed extent must match conversation end")
                    bar.toggle()
                    await pilot.pause()
                    packed()
                    bar.toggle()
                    await pilot.pause()
                    packed()
                for bar in (left, right):
                    actions = bar.query_one("#sidebar-layout-actions")
                    arrows = [item.render().plain for item in actions.children
                              if isinstance(item, SidebarAction) and item.action != "float"]
                    check(arrows == ["<──", "──>"], "arrows must be left then right")
                    button = bar.query_one("#sidebar-float", SidebarAction)
                    check(app.get_widget_at(button.region.x, button.region.y)[0] is button,
                          "Float/Push must stay clickable on narrow same-side bars")
            check(app._exception is None, "application raised an exception")
        await asyncio.get_running_loop().shutdown_default_executor()
    assert not failures, "\n".join(failures)
    print("header/sidebar screenshot regressions passed")


if __name__ == "__main__":
    asyncio.run(main())
