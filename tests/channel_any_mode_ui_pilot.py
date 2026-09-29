"""A channel menu exposes the core member-activity mode without hiding unread traffic."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp, wait_channel_roster
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


def group(sidebar: CommsSidebar, name: str) -> ChannelGroup:
    return next(row for row in sidebar.query(ChannelGroup) if row.row.target_name == name)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-any-mode-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        comms.registry.declare(Thread("alice", frozenset({"team"}), str(root)))
        comms.registry.declare(Thread("bob", frozenset({"other"}), str(root)))
        comms.messaging.send("alice", "#team", "exact route")
        comms.messaging.send("alice", "bob", "outbound from member")
        comms.messaging.send("bob", "alice", "inbound to member")
        comms.messaging.send("bob", "#other", "unrelated route")
        assert [m.body for m in comms.views.channel_display_page("#team").messages] == ["exact route"]

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            owner = app.selected_mode
            sidebar = await wait_channel_roster(app, pilot, "#team")
            await pilot.click(group(sidebar, "#team").row, button=3)
            await pilot.pause()
            item = next(item for item in app.screen.query(ContextMenuItem)
                        if item.action == "any_mode")
            assert "Show member activity" in item.render().plain
            await pilot.click(item)
            await pilot.pause()
            assert wire(root / "wire").channels.catalog.read().resolve("#team").any_mode
            assert [m.body for m in comms.views.channel_display_page("#team").messages] == [
                "exact route", "outbound from member", "inbound to member",
            ]
            assert comms.views.viewer_snapshot(str(root)).channel_unread["#team"] == 3

            await channel_target("#team").open(NavigationContext(app, owner, root, "alice"))
            chat = app.screen.query_one(CommsChatView)
            async with asyncio.timeout(5):
                while not chat._history_initialized:
                    await pilot.pause(.02)
            assert [message.body for message, _ in chat._history] == [
                "exact route", "outbound from member", "inbound to member",
            ]
            await app.switch_mode(owner)
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)

            await pilot.click(group(sidebar, "#team").row, button=3)
            await pilot.pause()
            item = next(item for item in app.screen.query(ContextMenuItem)
                        if item.action == "any_mode")
            assert "Show channel only" in item.render().plain
            await pilot.click(item)
            await pilot.pause()
            assert not wire(root / "wire").channels.catalog.read().resolve("#team").any_mode
            assert [m.body for m in comms.views.channel_display_page("#team").messages] == ["exact route"]

            await pilot.click(group(sidebar, "#any").row, button=3)
            await pilot.pause()
            assert all(item.action != "any_mode" for item in app.screen.query(ContextMenuItem))
            await pilot.press("escape")
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("channel menu toggles member activity and keeps unpainted traffic unread")


if __name__ == "__main__":
    asyncio.run(main())
