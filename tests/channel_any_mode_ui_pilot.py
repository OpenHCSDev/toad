"""A channel menu exposes the core member-activity mode without hiding unread traffic."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
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
        comms.register(Thread("alice", frozenset({"team"}), str(root)))
        comms.register(Thread("bob", frozenset({"other"}), str(root)))
        comms.send("alice", "#team", "exact route")
        comms.send("alice", "bob", "outbound from member")
        comms.send("bob", "alice", "inbound to member")
        comms.send("bob", "#other", "unrelated route")
        assert [m.body for m in comms.channel_display_page("#team").messages] == ["exact route"]

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            sidebar = app.screen.query_one(CommsSidebar)
            await pilot.click(group(sidebar, "#team").row, button=3)
            await pilot.pause()
            item = next(item for item in app.screen.query(ContextMenuItem)
                        if item.action == "any_mode")
            assert "Show member activity" in item.render().plain
            await pilot.click(item)
            await pilot.pause()
            assert wire(root / "wire").channel_catalog.resolve("#team").any_mode
            assert [m.body for m in comms.channel_display_page("#team").messages] == [
                "exact route", "outbound from member", "inbound to member",
            ]
            assert comms.viewer_snapshot(str(root)).channel_unread["#team"] == 3

            await app.open_comms_session(
                owner_mode=owner, project_path=root, me="alice",
                target="#team", kind="channel",
            )
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
            assert not wire(root / "wire").channel_catalog.resolve("#team").any_mode
            assert [m.body for m in comms.channel_display_page("#team").messages] == ["exact route"]

            await pilot.click(group(sidebar, "#any").row, button=3)
            await pilot.pause()
            assert all(item.action != "any_mode" for item in app.screen.query(ContextMenuItem))
            await pilot.press("escape")
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("channel menu toggles member activity and keeps unpainted traffic unread")


if __name__ == "__main__":
    asyncio.run(main())
