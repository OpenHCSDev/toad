"""Visited-tab Back/Forward controls and the native tab-strip scrollbar."""

import asyncio
import os
import tempfile
from pathlib import Path

from runtime_fixture import ToadApp
from toad.widgets.session_tabs import SessionLabel, SessionsTabs
from toad.widgets.side_bar import SideBar, TabHistoryButton, TabHistoryControls

from agent_comms import Thread, wire


async def wait_for(pilot, condition):
    async with asyncio.timeout(8):
        while not condition():
            await pilot.pause(.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-tab-history-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        wire(root / "wire").register(Thread("owner", frozenset(), str(root)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause()
            first = app.current_mode
            first_screen = app.screen
            first_screen.conversation.prompt.text = "Preserve first draft"
            left = first_screen.query_one("#channels-sidebar", SideBar)
            controls = first_screen.query_one(TabHistoryControls)
            header = first_screen.query_one("#tab-navigation-header")
            assert controls.parent is header
            assert first_screen.query_one(SessionsTabs).parent is header
            assert controls.region.y == first_screen.query_one(SessionsTabs).region.y
            assert controls.region.y == 0
            assert controls.query_one("#tab-back", TabHistoryButton).region.width == 7
            assert controls.query_one("#tab-back", TabHistoryButton).region.height == 2
            assert controls.query_one("#tab-back", TabHistoryButton).has_class("-unavailable")
            assert controls.query_one("#tab-forward", TabHistoryButton).has_class("-unavailable")
            assert controls.query_one("#tab-back", TabHistoryButton).disabled
            assert not first_screen.query_one("#thread-sidebar", SideBar).query(TabHistoryControls)
            assert controls.region.y < left.region.y
            assert controls.region.y < left.query_one("CollapsibleTitle").region.y
            left.collapsed = True
            await pilot.pause()
            assert controls.display and controls in first_screen._compositor.visible_widgets
            left.collapsed = False
            await pilot.pause()
            assert controls.display

            channel = await app.open_comms_session(
                owner_mode=first, project_path=root, me="owner", target="#all", kind="channel")
            await pilot.pause()
            assert app.current_mode == channel
            assert app.screen.query_one(SessionsTabs).display
            assert app.screen.query_one(SessionsTabs).region.y == 0
            assert not app.screen.query_one("#tab-back", TabHistoryButton).has_class("-unavailable")
            assert not app.screen.query_one("#tab-back", TabHistoryButton).disabled
            assert app.screen.query_one("#tab-forward", TabHistoryButton).has_class("-unavailable")
            channel_left = app.screen.query_one("#channels-sidebar", SideBar)
            channel_left.collapsed = True
            await pilot.pause()
            assert (app.screen.query_one(TabHistoryControls)
                    in app.screen._compositor.visible_widgets)
            assert await pilot.click("#tab-back")
            await wait_for(pilot, lambda: app.current_mode == first)
            assert await pilot.click("#tab-forward")
            await wait_for(pilot, lambda: app.current_mode == channel)
            second = (await app.new_session_screen(app.get_main_screen)).mode_name
            second_screen = app.screen
            second_screen.conversation.prompt.text = "Preserve second draft"

            assert await pilot.click("#tab-back")
            await wait_for(pilot, lambda: app.current_mode == channel)
            assert await pilot.click("#tab-back")
            await wait_for(pilot, lambda: app.current_mode == first)
            assert first_screen.conversation.prompt.text == "Preserve first draft"
            assert await pilot.click("#tab-forward")
            await wait_for(pilot, lambda: app.current_mode == channel)
            assert await pilot.click("#tab-forward")
            await wait_for(pilot, lambda: app.current_mode == second)
            assert second_screen.conversation.prompt.text == "Preserve second draft"

            # A direct selection after Back branches history, without closing
            # the other tab or adding another view to the strip.
            assert await pilot.click("#tab-back")
            await wait_for(pilot, lambda: app.current_mode == channel)
            label = app.screen.query_one(SessionsTabs).query_one(f"#{first}", SessionLabel)
            assert await pilot.click(label)
            await wait_for(pilot, lambda: app.current_mode == first)
            assert app.screen.query_one("#tab-forward", TabHistoryButton).has_class("-unavailable")
            assert {tab.mode_name for tab in app.open_tabs} == {first, channel, second}

            preview_path = root / "readme.md"
            preview_path.write_text("# Preview stays navigable\n")
            preview = await app.open_file_preview(preview_path)
            await pilot.pause()
            assert (app.screen.query_one(TabHistoryControls).region.y
                    == app.screen.query_one(SessionsTabs).region.y == 0)
            preview_back = app.screen.query_one("#tab-back", TabHistoryButton)
            assert await pilot.click("#tab-back"), (
                preview_back.region, preview_back.display,
                preview_back in app.screen._compositor.visible_widgets,
                preview_back.has_class("-unavailable"),
            )
            await wait_for(pilot, lambda: app.current_mode == first)
            assert await pilot.click("#tab-forward")
            await wait_for(pilot, lambda: app.current_mode == preview)
            await app.close_session_mode(preview)
            assert app.current_mode == first
            assert preview not in app._tab_history
            await app.close_session_mode(channel)
            assert channel not in app._tab_history
            assert {tab.mode_name for tab in app.open_tabs} == {first, second}
            assert first_screen.conversation.prompt.text == "Preserve first draft"

            # Long labels and many open tabs expose a 1-cell horizontal
            # scrollbar below the native underline without changing tab order.
            for _ in range(7):
                await app.new_session_screen(app.get_main_screen)
            await pilot.pause()
            tabs = app.screen.query_one(SessionsTabs)
            assert tabs.region.y == 0
            assert tabs.max_scroll_x > 0
            assert tabs.show_horizontal_scrollbar
            assert tabs.scrollbar_size_horizontal == 1
            assert tabs.region.height == 3
            tabs.scroll_to(x=tabs.max_scroll_x, animate=False, immediate=True)
            await pilot.pause()
            assert tabs.scroll_x == tabs.max_scroll_x
            tabs.horizontal_scrollbar.action_scroll_up()
            await wait_for(pilot, lambda: tabs.scroll_x < tabs.max_scroll_x)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("tab history: Back/Forward, branches, closed tabs, drafts, and horizontal scroll passed")


if __name__ == "__main__":
    asyncio.run(main())
