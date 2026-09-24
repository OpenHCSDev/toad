"""Persistent native unread counts reach sidebar/tabs; Start uses the core tool."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from agent_comms.runtime import socket_path
from runtime_fixture import ToadApp
from toad.acp.messages import TranscriptSnapshot
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.session_sidebar import ThreadStatusRow
from toad.widgets.session_tabs import SessionLabel


def reply(path, text):
    with path.open("a") as stream:
        stream.write(json.dumps({"type": "message", "message": {"role": "assistant", "content": text}}) + "\n")


async def refresh(app, pilot):
    sidebar = app.screen.query_one(CommsSidebar)
    await sidebar._read_snapshot(app.coordination_wire.revision())
    await pilot.pause()
    return sidebar


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-thread-unread-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
                          AGENT_COMMS_AGENT_BIN="/bin/echo", AGENT_COMMS_AGENT_MODELS="test/model")
        comms = wire(root / "wire")
        source = root / "session.jsonl"
        source.touch()
        comms.register(Thread("worker", frozenset({"team"}), str(root), session_file=str(source)))
        stopped_source = root / "stopped.jsonl"
        stopped_source.touch()
        comms.register(Thread("stopped", frozenset({"team"}), str(root), session_file=str(stopped_source)))
        comms.registry.unregister("stopped")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(130, 45)) as pilot:
            await pilot.pause()
            owner_mode, main_screen = app.current_mode, app.screen
            main_screen._coordination_root = str(comms.root.resolve())
            main_screen._comms_thread = "worker"
            conversation = main_screen.conversation
            reply(source, "Already viewed\n\n" + "\n".join(f"- visible line {i}" for i in range(45)))
            page = comms.thread_transcript_page("worker")
            conversation.post_message(TranscriptSnapshot(page.events, page))
            await pilot.pause()
            await refresh(app, pilot)
            assert comms.viewer_snapshot(str(root)).thread_unread["worker"] == 0

            channel_mode = await app.open_comms_session(owner_mode=owner_mode, project_path=root,
                                                        me="worker", target="#team", kind="channel")
            await pilot.pause()
            reply(source, "New reply while another tab is selected")
            sidebar = await refresh(app, pilot)
            assert app.screen.query_one(f"#{owner_mode}", SessionLabel).render().plain.endswith("(1)")
            group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#team")
            if not group.expanded:
                group.toggle_members()
            await pilot.pause()
            worker_row = next(row for row in group.query(ThreadStatusRow) if row.thread_name == "worker")
            assert "(1)" in worker_row.render().plain and worker_row.has_class("-unread")
            # Hidden snapshots cannot mark a thread read.
            page = comms.thread_transcript_page("worker")
            conversation.post_message(TranscriptSnapshot(page.events, page))
            await pilot.pause()
            await refresh(app, pilot)
            assert app.open_tabs[0].unread == 1
            conversation.window.scroll_relative(y=-4, animate=False, immediate=True)
            await app.switch_mode(owner_mode)
            await pilot.pause()
            await refresh(app, pilot)
            assert comms.viewer_snapshot(str(root)).thread_unread["worker"] == 1
            conversation.window.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            await refresh(app, pilot)
            assert comms.viewer_snapshot(str(root)).thread_unread["worker"] == 0
            assert app.screen.query_one(f"#{owner_mode}", SessionLabel).render().plain.endswith("worker")

            comms.send("worker", "#team", "Unread channel tab")
            await refresh(app, pilot)
            assert app.screen.query_one(f"#{channel_mode}", SessionLabel).render().plain.endswith("(1)")
            await app.switch_mode(channel_mode)
            await pilot.pause()
            chat = app.screen.query_one(CommsChatView)
            await chat._refresh()
            await refresh(app, pilot)
            assert not next(tab for tab in app.open_tabs if tab.mode_name == channel_mode).unread

            sidebar = app.screen.query_one(CommsSidebar)
            group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#team")
            if not group.expanded:
                group.toggle_members()
            await pilot.pause()
            stopped_row = next(row for row in group.query(ThreadStatusRow) if row.thread_name == "stopped")
            stopped_row.scroll_visible(animate=False)
            await pilot.pause()
            chat.prompt.text = "Keep my draft"
            stopped_view = await app.open_thread_session(
                owner_mode=owner_mode, project_path=root, target="stopped",
            )
            await pilot.pause()
            assert app.current_mode == stopped_view
            assert comms.registry.status("stopped").value == "stopped"
            await app.switch_mode(channel_mode)
            await pilot.pause()
            assert chat.prompt.text == "Keep my draft"
            await pilot.click(stopped_row, button=3)
            await pilot.pause()
            item = next(item for item in app.screen.query(ContextMenuItem) if item.action == "comms_start")
            await pilot.click(item)
            async with asyncio.timeout(15):
                while not (comms.registry.status("stopped").active and
                           socket_path(comms.root, comms.registry.require("stopped").pid).exists()):
                    await pilot.pause(.05)
            assert chat.prompt.text == "Keep my draft"
            assert app.current_mode == channel_mode
            await refresh(app, pilot)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("thread unread/start: sidebar + thread/channel tabs, visible-only read receipts, real menu start passed")


if __name__ == "__main__":
    asyncio.run(main())
