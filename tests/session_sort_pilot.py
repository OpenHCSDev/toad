"""Header sorting and stable local/remote positions through real ACP attachment."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from agent_comms import Activity, ActivityState, Message, MessageType, Thread, TranscriptCursor, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar, ChannelGroup, ThreadRow
from toad.widgets.session_sort import ChannelListSort, SessionSort
from toad.widgets.side_bar import SideBarCollapsible


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(0.05)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-sort-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_BIN="/bin/echo",
            AGENT_COMMS_AGENT_ARGS="--model test/model",
            AGENT_COMMS_AGENT_MODELS="test/model",
        )
        comms = wire(root / "wire")
        history = root / "history.jsonl"
        history.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {"role": "assistant", "content": "Saved reply"},
                }
            )
            + "\n"
        )
        for name, created, activity, sent in (
            ("old", 100, 300, 400),
            ("new", 200, 250, 500),
        ):
            comms.register(
                Thread(
                    name=name,
                    tags=frozenset(),
                    worktree=str(project),
                    session_file=str(history),
                    created_at=created,
                    task="An original task must not become the sidebar status. " * 30,
                )
            )
            comms.set_agent_info(name, model="provider/a-very-long-model-name")
            comms.activity.emit(
                Activity(thread=name, state=ActivityState.WORKING, timestamp=activity)
            )
            comms.bus.send(
                Message(
                    sender=name,
                    target="#all",
                    body=f"from {name}",
                    type=MessageType.INFO,
                    timestamp=sent,
                )
            )
            comms.acknowledge(name)
        comms.acknowledge("old")
        # Agent inbox acknowledgements do not clear the human's native-history
        # unread badge. This sorting fixture compares rows with an already-read
        # saved reply before and after opening the view.
        comms.mark_thread_view_read(
            "old", worktree=str(project),
            through=TranscriptCursor(str(history), history.stat().st_size),
        )
        agent = {
            "name": "Agent Comms",
            "identity": "sort-test",
            "short_name": "sort-test",
            "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
            "protocol": "acp",
        }
        app = ToadApp(agent_data=agent, project_dir=str(project))

        def sort_control():
            return next(group for group in app.screen.query(ChannelGroup)
                        if group.row.target_name == "#any").query_one(SessionSort)

        def order():
            sidebar = app.screen.query_one(CommsSidebar)
            result = []
            for row in sidebar._ordered_rows():
                if not row.target_name.startswith("#"):
                    result.append(row.target_name)
            return result

        async with app.run_test(size=(120, 40)) as pilot:
            await until(
                lambda: getattr(app.screen, "conversation", None) is not None
                and app.screen.conversation.agent_ready
            )
            await pilot.pause()
            parent_mode = app.current_mode
            sidebar = app.screen.query_one(CommsSidebar)
            sidebar._refresh()
            await pilot.pause()
            assert order() == ["project", "new", "old"], order()
            remote = next(
                row for row in sidebar.query(CommsRow) if row.target_name == "old"
            )
            closed_status = remote.render().plain
            assert closed_status == "✓ old\n  Ready"
            assert remote.region.height == 2
            control = sort_control()
            panel = control.query_ancestor(SideBarCollapsible)
            title = control.query_ancestor(ChannelGroup).row
            assert control.region.y == title.region.y
            assert control.region.right == control.parent.content_region.right
            assert await pilot.click(
                next(row for row in sidebar.query(CommsRow) if row.target_name == "old")
            )
            await until(
                lambda: app.current_mode != parent_mode
                and app.screen.conversation.agent_ready
            )
            old_mode = app.current_mode
            await pilot.pause()
            opened = next(
                row for row in app.screen.query(ThreadRow) if row.mode_name == old_mode
            )
            assert opened.render().plain == closed_status
            assert opened.region.height == 2
            assert order() == ["project", "new", "old"], order()
            app.screen.conversation.prompt.text = "Unsubmitted manual input"
            comms.heartbeat("old")
            app.screen.query_one(CommsSidebar)._refresh()
            await pilot.pause()
            assert order() == ["project", "new", "old"], order()

            async def choose(criterion):
                control = sort_control()
                right = control.region.right
                assert await pilot.click(control)
                await pilot.pause()
                assert isinstance(app.screen, ContextMenu)
                assert app.screen.query_one("#context-menu").region.right == right
                item = next(
                    item
                    for item in app.screen.query(ContextMenuItem)
                    if item.action == criterion
                )
                assert await pilot.click(item)
                await pilot.pause()
                assert comms.channel_catalog.resolve("#any").order.value == criterion
                assert (
                    not sort_control()
                    .query_ancestor(SideBarCollapsible)
                    .collapsed
                )

            await choose("last_message_sent")
            assert order() == ["new", "old", "project"], order()
            comms.bus.send(
                Message(
                    sender="old",
                    target="#all",
                    body="new outgoing",
                    type=MessageType.INFO,
                    timestamp=600,
                )
            )
            app.screen.query_one(CommsSidebar)._refresh()
            await pilot.pause()
            assert order() == ["old", "new", "project"], order()
            await choose("last_activity")
            assert order() == ["old", "new", "project"], order()
            comms.activity.emit(
                Activity(thread="new", state=ActivityState.WORKING, timestamp=700)
            )
            app.screen.query_one(CommsSidebar)._refresh()
            await pilot.pause()
            assert order() == ["new", "old", "project"], order()
            await app.switch_mode(parent_mode)
            await pilot.pause()
            assert order() == ["new", "old", "project"], order()
            assert "Last activity" in sort_control().render().plain
            await app.switch_mode(old_mode)
            await pilot.pause()
            assert order() == ["new", "old", "project"], order()
            # Backend status has the same compact rendering regardless of an
            # open tab, and UI-only state updates cannot overwrite that status.
            detail = "Checking the workspace and running verification. " * 3
            for name in ("old", "new"):
                comms.set_activity(name, ActivityState.WORKING, detail)
            sidebar = app.screen.query_one(CommsSidebar)
            sidebar._refresh()
            await pilot.pause()
            opened = next(
                row for row in sidebar.query(ThreadRow) if row.mode_name == old_mode
            )
            unopened = next(
                row for row in sidebar.query(CommsRow) if row.target_name == "new"
            )
            assert (
                opened.render().plain.splitlines()[1]
                == unopened.render().plain.splitlines()[1]
            )
            assert opened.has_class("-busy") and unopened.has_class("-busy")
            app.session_tracker.update_session(
                old_mode, state="idle", summary="Ready from the view"
            )
            await pilot.pause()
            assert opened.render().plain.splitlines()[1].startswith("  Working")
            for width in (96, 120):
                await pilot.resize_terminal(width, 40)
                await pilot.pause()
                assert opened.region.height == unopened.region.height == 2, (
                    width, opened.region, unopened.region, opened.is_attached,
                    unopened.is_attached, opened.classes, unopened.classes,
                )
                assert "original task" not in unopened.render().plain
                assert "provider/" not in unopened.render().plain
            for name in ("old", "new"):
                comms.set_activity(name, ActivityState.IDLE)
            sidebar._refresh()
            await pilot.pause()
            assert opened.render().plain == "✓ old\n  Ready"
            assert unopened.render().plain == "✓ new\n  Ready"
            comms.stop("new")
            sidebar._refresh()
            await pilot.pause()
            assert unopened.render().plain == "○ new\n  Stopped"
            panel = app.screen.query_one(SessionSort).query_ancestor(SideBarCollapsible)
            assert await pilot.click(panel.query_one("CollapsibleTitle"))
            await pilot.pause()
            assert panel.collapsed and panel.region.height == 1
            # The member sort is hidden with the panel. Its old virtual region
            # is not the visible Channels header after tab controls were added.
            assert panel.query_one(ChannelListSort).region.y == panel.region.y
    print(
        "session sorting: all criteria, selection stability, shared setting and header layout passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
