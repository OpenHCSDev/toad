"""Experimental virtual roster keeps native channel/member routing intact."""

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms import Thread, wire
from rich.style import Style as RichStyle
from runtime_fixture import ToadApp
from textual.events import Click
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.comms_chat import session_thread_name
from toad.widgets.virtual_channel_list import VirtualChannelList


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-virtual-roster-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
                          TOAD_BENCH_VIRTUAL_CHANNELS="1")
        name = session_thread_name(root)
        comms = wire(root / "wire")
        comms.register(Thread(name, frozenset({"alpha"}), str(root), pid=os.getpid()))
        comms.register(Thread("archived", frozenset({"alpha"}), str(root), pid=0))
        comms.stop("archived")
        comms.archive("archived")
        comms.create_tag("beta")
        for index in range(30):
            comms.create_tag(f"extra-{index:02d}")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause()
            first = app.current_mode
            sidebar = app.screen.query_one(CommsSidebar)
            async with asyncio.timeout(5):
                while sidebar._last_snapshot is None:
                    await pilot.pause(.02)
            roster = sidebar.query_one(VirtualChannelList)
            assert roster.option_count >= 35
            assert roster.get_option_index("new-session") == 0
            assert roster.styles.text_wrap == "nowrap"
            assert not sidebar.query("ChannelGroup"), "Virtual roster still mounted every group"
            assert "member:#alpha:archived" not in sidebar._virtual_targets
            app.settings.set("sidebar.show_archived", True)
            await sidebar.sync_sessions()
            roster.highlighted = roster.get_option_index("channel:#alpha")
            roster.focus()
            await pilot.press("space")
            await pilot.pause()
            assert "member:#alpha:archived" in sidebar._virtual_targets
            roster._update_lines()
            header_index = roster.get_option_index("channel:#alpha")
            member_index = roster.get_option_index("member:#alpha:archived")
            assert roster._line_cache.heights[header_index] == 1
            assert roster._line_cache.heights[member_index] == 2
            header = roster.get_option_index("channel:#alpha")
            for expanded in (False, True):
                disclosure = Click(roster, 0, 2, 0, 0, 1, False, False, False,
                                   screen_x=roster.region.x,
                                   screen_y=roster.region.y + 2,
                                   style=RichStyle.from_meta({"option": header}))
                roster._forward_event(disclosure)
                await pilot.pause()
                assert ("member:#alpha:archived" in sidebar._virtual_targets) is expanded
                assert app.current_mode == first, "Disclosure inadvertently opened a tab"
            app.settings.set("sidebar.show_archived", False)
            await sidebar.sync_sessions()
            assert "member:#alpha:archived" not in sidebar._virtual_targets
            roster.highlighted = roster.get_option_index("channel:#alpha")
            label_click = Click(roster, 2, 2, 0, 0, 1, False, False, False,
                                screen_x=roster.region.x + 2,
                                screen_y=roster.region.y + 2,
                                style=RichStyle.from_meta({"option": roster.highlighted}))
            roster._forward_event(label_click)
            async with asyncio.timeout(6):
                while (getattr(app.screen, "target", None) != "#alpha"
                       or app.screen.query_one_optional(CommsSidebar) is None):
                    await pilot.pause(.02)
            channel = app.current_mode
            assert first != channel
            await pilot.pause()
            await app.screen.query_one(CommsSidebar).sync_sessions()
            on_channel = app.screen.query_one(VirtualChannelList)
            on_channel.highlighted = on_channel.get_option_index("channel:#any")
            on_channel.action_select()
            async with asyncio.timeout(6):
                while (getattr(app.screen, "target", None) != "#any"
                       or app.screen.query_one_optional(CommsSidebar) is None):
                    await pilot.pause(.02)
            any_mode = app.current_mode
            assert any_mode != channel
            await pilot.pause()
            await app.screen.query_one(CommsSidebar).sync_sessions()
            members = app.screen.query_one(VirtualChannelList)
            member_id = f"member:#any:{name}"
            assert member_id in app.screen.query_one(CommsSidebar)._virtual_targets
            members.highlighted = members.get_option_index(member_id)
            members.action_select()
            async with asyncio.timeout(6):
                while app.current_mode != first:
                    await pilot.pause(.02)
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.focus_current_session()
            current_list = sidebar.query_one(VirtualChannelList)
            assert current_list.highlighted_option.id == member_id
            filled = [option.id for option in current_list.options
                      if any("ansi_magenta" in str(span.style)
                             and "ansi_black" in str(span.style)
                             for span in getattr(option.prompt, "spans", ()))]
            assert filled == [member_id], filled
            current_list.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            remembered = current_list.scroll_y
            assert remembered > 0
            await app.switch_mode(any_mode)
            await app.switch_mode(first)
            await pilot.pause()
            assert current_list.scroll_y == remembered, "Virtual channel scroll did not survive switching"

            current_list.scroll_home(animate=False, immediate=True)
            await pilot.pause()
            index = current_list.get_option_index("channel:#any")
            click = Click(current_list, 4, 2, 0, 0, 3, False, False, False,
                          screen_x=current_list.region.x + 4,
                          screen_y=current_list.region.y + 2,
                          style=RichStyle.from_meta({"option": index}))
            current_list._forward_event(click)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu), "Right-click did not open a channel menu"
            assert app.current_mode == first
            await pilot.press("escape")
            await pilot.pause()
            assert app._exception is None
            print({"first_paint_route": "real OptionSelected", "channels": ("#alpha", "#any"),
                   "existing_session_reused": app.current_mode == first,
                   "virtual_scroll_restored": True,
                   "right_click_menu": True,
                   "sidebar_widget_count": len(list(sidebar.walk_children()))})
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
