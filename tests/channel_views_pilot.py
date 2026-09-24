"""Persistent comms tabs and lazy model-owned multi-tag memberships."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import ActivityState, ChannelSort, Thread, ThreadSort, wire
from toad.app import ToadApp
from toad.screens.comms import CommsScreen
from toad.screens.main import MainScreen
from toad.widgets.comms_sidebar import CommsSidebar, CommsRow, ChannelGroup, ChannelDisclosure, NewSessionButton
from toad.widgets.session_sort import ChannelListSort, SessionSort
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.irc_message import IRCMessage, MembershipNotice
from toad.widgets.channel_participants import ChannelParticipants
from toad.widgets.user_input import UserInput
from toad.widgets.conversation import Loading
from textual.worker import Worker, WorkerState


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-channels-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        for name, tags in ((root.name, set()), ("api-agent", {"api"}), ("ui-agent", {"ui"}), ("other", set())):
            comms.register(Thread(name, frozenset(tags), str(root), pid=os.getpid()))
        comms.set_channel("engineering", frozenset({"api", "ui"}))
        order_saved = asyncio.Event()

        def worker_changed(message):
            if (isinstance(message, Worker.StateChanged)
                    and message.worker.name == "_save_order"
                    and message.state is WorkerState.SUCCESS):
                order_saved.set()

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 50), message_hook=worker_changed) as pilot:
            await pilot.pause()
            await app.action_set_footer(False)
            assert app.settings.get("ui.footer", bool) is False
            assert app.has_class("-hide-footer")
            owner = app.current_mode
            sidebar = app.screen.query_one(CommsSidebar)
            assert all(isinstance(child, (NewSessionButton, ChannelGroup)) for child in sidebar.children)
            assert {group.row.target_name for group in sidebar.query(ChannelGroup)} >= {"#any", "#none", "#engineering"}
            none_group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#none")
            none_group.query_one(SessionSort).action_choose_sort()
            await pilot.pause()
            await pilot.click(next(item for item in app.screen.query(ContextMenuItem) if item.action == "last_activity"))
            await pilot.pause()
            assert comms.channel_catalog.resolve("#none").order is ThreadSort.LAST_ACTIVITY
            assert comms.channel_catalog.resolve("#any").order is ThreadSort.CREATED
            group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#engineering")
            assert len(group.query(CommsRow)) == 1
            group.query_one(ChannelDisclosure).focus()
            await pilot.press("enter")
            await pilot.pause()
            assert set(group._members) == {"api-agent", "ui-agent"}
            other = wire(root / "wire")
            other.update_tags("other", add=frozenset({"api"}))
            sidebar._refresh()
            await pilot.pause()
            assert set(group._members) == {"api-agent", "ui-agent", "other"}
            group.toggle_members()
            await pilot.pause()
            assert len(group.query(CommsRow)) == 1
            await pilot.click(group.row)
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            engineering = app.current_mode
            chat = app.screen.query_one("CommsChatView")
            assert chat.agent is None and chat._shell is None
            assert chat._directory_watcher is None
            chat.prompt.text = "user channel test"
            chat.prompt.focus()
            await pilot.press("enter")
            await pilot.pause()
            sent = comms.channel_history("#engineering")
            authored = [message for message in sent if message.membership is None]
            assert len(authored) == 1 and authored[0].sender == "user"
            assert len(chat.query(MembershipNotice)) == 1
            assert len(chat.query(IRCMessage)) == 1
            assert not chat.query(UserInput) and not chat.query(Loading)
            assert chat.turn != "agent"
            assert not chat.prompt.query("#info-container")
            chat.prompt.text = ""
            chat.prompt.focus()
            await pilot.press("up")
            await pilot.pause()
            assert chat.prompt.text == "user channel test"
            await pilot.press("down")
            await pilot.pause()
            assert chat.prompt.text == ""
            comms.begin_turn("api-agent", "api-turn")
            comms.begin_turn("ui-agent", "ui-turn")
            await chat._refresh()
            roster = chat.query_one(ChannelParticipants)
            assert "api-agent" in roster.names.render().plain and "ui-agent" in roster.names.render().plain
            assert "other" not in roster.names.render().plain
            comms.finish_turn("api-agent", "api-turn")
            comms.finish_turn("ui-agent", "ui-turn")
            assert roster.region.bottom <= chat.prompt.region.y
            chat.prompt.text = "first second"
            chat.prompt.focus()
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert chat.prompt.text == "first " and app.current_mode == engineering
            await pilot.press("ctrl+j")
            await pilot.pause()
            assert chat.prompt.text == "first \n" and app.current_mode == engineering
            app.screen.query_one("Prompt").text = "draft stays here"
            await pilot.click(f"SessionLabel#{owner}")
            await pilot.pause()
            assert app.screen.query_one(f"SessionLabel#{engineering}")
            any_mode = await app.open_comms_session(owner_mode=owner, project_path=root,
                                                   me=root.name, target="#any", kind="irc")
            await pilot.pause()
            assert {label.id for label in app.screen.query(SessionLabel)} == {owner, engineering, any_mode}
            any_chat = app.screen.query_one("CommsChatView")
            any_chat.prompt.focus()
            await pilot.press("up")
            await pilot.pause()
            assert any_chat.prompt.text == ""
            await pilot.click(f"SessionLabel#{engineering}")
            await pilot.pause()
            assert app.screen.query_one("Prompt").text == "draft stays here"
            await pilot.click(f"#close-{any_mode}")
            await pilot.pause()
            assert app.current_mode == engineering
            assert not app.screen.query(f"SessionLabel#{any_mode}")
            await app.switch_mode(owner)
            await pilot.pause()
            assert {label.id for label in app.screen.query(SessionLabel)} == {owner, engineering}
            second = await app.new_session_screen(lambda: MainScreen(root))
            await pilot.pause()
            # The same channel opened from another agent tab must select the
            # existing mode and preserve its composer rather than create a copy.
            duplicate = await app.open_comms_session(
                owner_mode=second.mode_name, project_path=root,
                me="api-agent", target="#engineering", kind="channel",
            )
            await pilot.pause()
            assert duplicate == engineering
            assert app.screen.query_one("Prompt").text == "draft stays here"
            assert sum(tab.title == "#engineering" for tab in app.open_tabs) == 1
            # An old sidebar and a newly opened view must use the same model
            # order even when channels were created after the first view.
            comms.create_tag("z-last")
            comms.create_tag("a-first")
            await app.screen.query_one(CommsSidebar).sync_sessions()
            expected = [view.channel.name for view in comms.channel_views()]
            assert [group.row.target_name for group in app.screen.query(ChannelGroup)] == expected
            await app.switch_mode(owner)
            await pilot.pause()
            assert [group.row.target_name for group in app.screen.query(ChannelGroup)] == expected
            selector = app.screen.query_one(ChannelListSort)
            selector.action_choose_sort()
            await pilot.pause()
            assert {item.action for item in app.screen.query(ContextMenuItem)} == {
                order.value for order in ChannelSort
            } | {"show_stopped", "show_archived"}
            order_saved.clear()
            await pilot.click(next(item for item in app.screen.query(ContextMenuItem)
                                   if item.action == "last_user_input"))
            await pilot.pause()
            async with asyncio.timeout(5):
                await order_saved.wait()
            await app.screen.query_one(CommsSidebar).sync_sessions()
            assert selector.order is ChannelSort.LAST_USER_INPUT
            assert comms.channel_catalog.list_order is ChannelSort.LAST_USER_INPUT
            assert comms.channel_catalog.resolve("#none").order is ThreadSort.LAST_ACTIVITY
            await app.switch_mode(engineering)
            await pilot.pause()
            assert app.screen.query_one(ChannelListSort).order is ChannelSort.LAST_USER_INPUT
            group = next(group for group in app.screen.query(ChannelGroup)
                         if group.row.target_name == "#engineering")
            await pilot.click(group.row)
            await pilot.pause()
            assert app.current_mode == engineering
            assert sum(tab.title == "#engineering" for tab in app.open_tabs) == 1
            # The channel header must glow while any member is mid-turn or busy.
            comms.set_activity("ui-agent", ActivityState.WORKING, "Rendering")
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.sync_sessions()
            engineering_group = next(
                group for group in sidebar.query(ChannelGroup)
                if group.row.target_name == "#engineering"
            )
            await pilot.pause()
            assert engineering_group.row.has_class("-channel-active"), (
                "channel must indicate member activity: "
                + engineering_group.row.render().plain
            )
            comms.set_activity("ui-agent", ActivityState.IDLE, "")
            await sidebar.sync_sessions()
            await pilot.pause()
            assert not engineering_group.row.has_class("-channel-active")
            # Actual context-menu actions persist in the wire and render identically
            # in a second view. A member pin is scoped to its containing channel.
            await pilot.click(engineering_group.row, button=3)
            await pilot.pause()
            pin = next(item for item in app.screen.query(ContextMenuItem) if item.action == "pin")
            assert "Pin channel" in pin.render().plain
            await pilot.click(pin)
            await pilot.pause()
            await sidebar.sync_sessions()
            assert wire(root / "wire").channel_views()[0].channel.name == "#engineering"
            assert next(iter(sidebar.query(ChannelGroup))) is engineering_group
            assert engineering_group.row.render().plain.startswith("* ")
            if not engineering_group.expanded:
                engineering_group.toggle_members()
            await pilot.pause()
            await pilot.click(engineering_group._members["api-agent"], button=3)
            await pilot.pause()
            pin = next(item for item in app.screen.query(ContextMenuItem) if item.action == "pin")
            assert "Pin in this channel" in pin.render().plain
            await pilot.click(pin)
            await pilot.pause()
            await sidebar.sync_sessions()
            views = {view.channel.name: view for view in wire(root / "wire").channel_views()}
            assert views["#engineering"].pinned_members == {"api-agent"}
            assert not views["#any"].pinned_members
            assert engineering_group.member_rows[0].thread_name == "api-agent"
            assert engineering_group.member_rows[0].render().plain.startswith("* ")
            await app.switch_mode(owner)
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            engineering_group = next(iter(sidebar.query(ChannelGroup)))
            assert engineering_group.row.target_name == "#engineering"
            if not engineering_group.expanded:
                engineering_group.toggle_members()
            await pilot.pause()
            assert engineering_group.member_rows[0].thread_name == "api-agent"
            await pilot.click(engineering_group.member_rows[0], button=3)
            await pilot.pause()
            pin = next(item for item in app.screen.query(ContextMenuItem) if item.action == "pin")
            assert "Unpin from this channel" in pin.render().plain
            await pilot.click(pin)
            await pilot.pause()
            await pilot.click(engineering_group.row, button=3)
            await pilot.pause()
            pin = next(item for item in app.screen.query(ContextMenuItem) if item.action == "pin")
            assert "Unpin channel" in pin.render().plain
            await pilot.click(pin)
            await pilot.pause()
            views = {view.channel.name: view for view in comms.channel_views()}
            assert not views["#engineering"].channel.pinned
            assert not views["#engineering"].pinned_members
    print("channel views: lazy union membership, external tag updates, persistent tabs/drafts and inactive close passed")


if __name__ == "__main__":
    asyncio.run(main())
