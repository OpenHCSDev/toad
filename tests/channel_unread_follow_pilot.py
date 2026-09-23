"""Channel focus owns unread markers; late messages preserve explicit follow intent."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-channel-follow-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        names = [f"worker-{index}-long-display-name" for index in range(8)]
        for name in names:
            comms.register(Thread(name, frozenset({"talk"}), str(root), pid=os.getpid()))
        for index in range(50):
            comms.send(names[0], "#talk", f"Message {index}: " + "body " * 30)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            mode = await app.open_comms_session(
                owner_mode=owner, project_path=root, me=names[0], target="#talk", kind="channel",
            )
            await pilot.pause()
            chat = app.screen.query_one(CommsChatView)
            assert comms.viewer_snapshot(str(root)).channel_unread["#talk"] == 0
            assert chat.window.follows_tail
            for name in names:
                comms.begin_turn(name, name)
            comms.send(names[0], "#talk", "ARRIVED_AFTER_ROSTER_GREW")
            await chat._refresh()
            await pilot.pause()
            assert chat.window.follows_tail and chat.window.scroll_y == chat.window.max_scroll_y
            assert any(message.body == "ARRIVED_AFTER_ROSTER_GREW" for message, _ in chat._history)
            chat.window.scroll_relative(y=-8, animate=False, immediate=True)
            await pilot.pause()
            position = chat.window.scroll_y
            comms.send(names[0], "#talk", "WAIT_UNTIL_I_RETURN")
            await chat._refresh()
            await pilot.pause()
            assert not chat.window.follows_tail and chat.window.scroll_y == position
            chat.window.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            assert chat.window.follows_tail
            await app.switch_mode(owner)
            comms.send(names[0], "#talk", "unread one")
            comms.send(names[0], "#talk", "unread two")
            comms.acknowledge(names[1])
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.sync_sessions()
            group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#talk")
            assert group.unread_badge.render().plain == "(2)"
            await app.switch_mode(mode)
            await pilot.pause()
            assert comms.viewer_snapshot(str(root)).channel_unread["#talk"] == 0
        # Deferred first-frame wire reads can still be finishing after the UI
        # closes; don't remove their test-owned files before the executor drains.
        await asyncio.get_running_loop().shutdown_default_executor()
    print("channel follow/unread: roster resize, arrivals, scroll-up, refocus and independent human cursors passed")


if __name__ == "__main__":
    asyncio.run(main())
