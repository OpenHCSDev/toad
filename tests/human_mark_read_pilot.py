"""The TUI menu clears human badges without advancing executor inbox cursors."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


async def click_ack(app, pilot, row):
    row.scroll_visible(animate=False)
    await pilot.pause()
    await pilot.click(row, button=3)
    await pilot.pause()
    await pilot.click(next(item for item in app.screen.query(ContextMenuItem)
                           if item.action == "comms_ack"))


async def until(predicate, pilot):
    async with asyncio.timeout(5):
        while not predicate():
            await pilot.pause(.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-mark-human-read-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        owner = root.name
        source = root / "sender.jsonl"
        source.write_text(json.dumps({"type": "message", "message": {
            "role": "assistant", "content": "Saved answer",
        }}) + "\n")
        comms.register(Thread(owner, frozenset({"ci"}), str(root)))
        comms.register(Thread("sender", frozenset({"ci"}), str(root), session_file=str(source)))
        human = comms.user_identity(str(root)).name
        comms.send("sender", owner, "Keep executor DM pending")
        comms.send("sender", "#ci", "Keep executor channel pending")
        comms.send("sender", human, "Human DM badge")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)
            await sidebar.sync_sessions()
            group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#ci")
            if not group.expanded:
                group.toggle_members()
            await pilot.pause()
            sender = group._members["sender"]
            assert "(1)" in sender.render().plain
            assert comms.viewer_snapshot(str(root)).channel_unread["#ci"] == 1
            await click_ack(app, pilot, sender)
            await until(lambda: comms.viewer_snapshot(str(root)).thread_unread["sender"] == 0, pilot)
            assert comms.viewer_snapshot(str(root)).unread.get("sender", 0) == 0
            assert comms.pending_count(owner, "sender") == 1
            assert comms.pending_count(owner, "#ci") == 1
            await sidebar.sync_sessions()
            await pilot.pause()
            assert "(1)" not in group._members["sender"].render().plain
            await click_ack(app, pilot, group.row)
            await until(lambda: comms.viewer_snapshot(str(root)).channel_unread["#ci"] == 0, pilot)
            assert comms.pending_count(owner, "#ci") == 1
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("Mark inbox read: native/DM/channel human badges clear; agent delivery remains unread")


if __name__ == "__main__":
    asyncio.run(main())
