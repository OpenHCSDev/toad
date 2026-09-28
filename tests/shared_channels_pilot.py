"""One native Channels tree survives new/loading/existing tabs and tab closure."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from agent_comms.comms import wire
from agent_comms.threads import Thread
from runtime_fixture import ToadApp, wait_channel_roster
from toad.acp.agent import Agent
from toad.agent import AgentReady
from toad.acp.messages import CoordinationUpdate
from toad.navigation_preparation import ThreadNavigationRequest
from toad.screens.pending_thread import PendingThreadScreen
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.side_bar import SideBar, SidebarResizeHandle


class FrameApp(ToadApp):
    expected_bar = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = []

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if (self.expected_bar is not None and screen is self.screen
                and renderable is not None and not self._batch_count):
            bar = screen.query_one_optional(ChannelsSidebar)
            self.frames.append((self.current_mode, bar is self.expected_bar,
                                bar is not None and any(row.target_name == "#all"
                                and row in screen._compositor.visible_widgets
                                for row in bar.roster._row_map.values())))


async def main():
    with TemporaryDirectory(prefix="toad-shared-channels-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        for name in ("owner", "peer"):
            comms.threads.register(Thread(name, frozenset({"fixture", "shared", "slow"}), str(root), pid=os.getpid()))
        comms.channels.create_tag("shared")

        async def start(agent, target):
            agent._message_target = target
            agent._task = asyncio.create_task(asyncio.sleep(0))
            target.post_message(AgentReady())

        app = FrameApp(project_dir=str(root))
        with patch.object(Agent, "start", start):
            async with app.run_test(size=(120, 42)) as pilot:
                roster = await wait_channel_roster(app, pilot, "#all", "#shared")
                bar = app.screen.query_one(ChannelsSidebar)
                bar.reveal()
                await pilot.pause()
                original_rows = dict(roster._row_map)
                original_tasks = {key: row._task for key, row in original_rows.items()}
                owner = app.current_mode
                right = app.screen.query_one("#thread-sidebar", SideBar)
                right.reveal()
                await pilot.pause()
                marker = next(row for row in original_rows.values() if row.target_name == "#all")
                cached_lines = dict(marker._styles_cache._cache)
                assert cached_lines
                app.expected_bar = bar
                second = (await app.new_session_screen(app.get_main_screen)).mode_name
                await wait_channel_roster(app, pilot, "#all")
                assert app.screen.query_one(ChannelsSidebar) is bar
                assert app.screen.query_one(CommsSidebar) is roster
                assert all(marker._styles_cache._cache.get(y) is line for y, line in cached_lines.items()), (
                    "Opening a tab discarded unchanged Channels paint")
                assert app.screen.query_one("#thread-sidebar", SideBar) is not right
                assert app.screen.query_one("#thread-sidebar", SideBar).collapsed
                handle = bar.query_one(SidebarResizeHandle)
                assert await pilot.mouse_down(handle, offset=(0, 4))
                assert app.mouse_captured is handle and handle._dragging
                try:
                    await app.switch_mode(owner)
                    await pilot.pause()
                    assert app.mouse_captured is None and not handle._dragging
                finally:
                    await pilot.mouse_up()
                await pilot.pause()
                assert not right.collapsed

                entered, release = Event(), Event()
                read = ThreadNavigationRequest.read

                def blocked(request):
                    entered.set()
                    assert release.wait(8)
                    return read(request)

                app.screen._agent = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                     "run_command": {"*": "/bin/false"}, "protocol": "acp"}
                with patch.object(ThreadNavigationRequest, "read", blocked):
                    opening = asyncio.create_task(app.open_thread_session(
                        owner_mode=owner, project_path=root, target="peer"))
                    try:
                        assert await asyncio.to_thread(entered.wait, 3)
                        assert isinstance(app.screen, PendingThreadScreen)
                        await pilot.pause()
                        assert app.screen.query_one(ChannelsSidebar) is bar
                        release.set()
                        thread = await asyncio.wait_for(opening, 8)
                    finally:
                        release.set()
                        await asyncio.gather(opening, return_exceptions=True)
                await wait_channel_roster(app, pilot, "#all")
                channel = await app.open_comms_session(owner_mode=owner, project_path=root,
                                                       me="owner", target="#shared", kind="channel")
                await wait_channel_roster(app, pilot, "#all")
                for mode in (second, thread, owner, channel, second):
                    await app.switch_mode(mode)
                    await pilot.pause()
                    assert app.screen.query_one(ChannelsSidebar) is bar
                    assert all(roster._row_map[key] is row for key, row in original_rows.items())
                    assert all(row._task is original_tasks[key] for key, row in original_rows.items())
                assert sum(isinstance(node, ChannelsSidebar) for node in app._registry) == 1
                assert app.frames and all(same and populated for _, same, populated in app.frames), app.frames
                app.expected_bar = None
                await app.close_session_mode(second)
                await pilot.pause()
                assert bar.is_attached and not bar._closed
                assert all(row.is_attached for row in original_rows.values())

                # Conversation composition may finish after leaving its tab.
                # Its completion must not find or rebind another tab's Channels.
                comms.channels.create_tag("slow")
                mount_entered, mount_release = asyncio.Event(), asyncio.Event()
                mount = CommsChatView.on_mount

                async def slow_mount(chat):
                    mount_entered.set()
                    await mount_release.wait()
                    await mount(chat)

                with patch.object(CommsChatView, "on_mount", slow_mount):
                    opening = asyncio.create_task(app.open_comms_session(
                        owner_mode=owner, project_path=root, me="owner", target="#slow", kind="channel"))
                    try:
                        await asyncio.wait_for(mount_entered.wait(), 3)
                        await app.switch_mode(owner)
                    finally:
                        mount_release.set()
                    delayed = await asyncio.wait_for(opening, 8)
                assert app.current_mode == owner and bar.screen is app.screen
                assert not app.get_screen_stack(delayed)[0].query(ChannelsSidebar)
                assert app._exception is None

                # The shared panel is also a single route-bound observer. An
                # old read released after a route replacement cannot publish.
                new_root = root / "other-wire"
                await app.get_screen_stack(owner)[0].on_coordination_update(CoordinationUpdate(
                    thread="owner", wire_root=str(root / "wire"), persistence="fixture", transport="fixture"))
                other = wire(new_root)
                other.threads.register(Thread("owner", frozenset({"new", "new-source"}), str(root), pid=os.getpid()))
                other.channels.create_tag("new-source")
                old_service = roster._wire
                read_entered, read_release = Event(), Event()
                original_read = old_service.views.viewer_snapshot

                def held_read(*args, **kwargs):
                    result = original_read(*args, **kwargs)
                    read_entered.set()
                    assert read_release.wait(8)
                    return result

                with patch.object(old_service.views, "viewer_snapshot", held_read):
                    roster._last_revision = None
                    roster._refresh()
                    try:
                        assert await asyncio.to_thread(read_entered.wait, 3)
                        os.environ["AGENT_COMMS_ROOT"] = str(new_root)
                        await app.new_session_screen(app.get_main_screen)
                        assert app.screen.query_one(ChannelsSidebar) is bar
                        read_release.set()
                        await wait_channel_roster(app, pilot, "#new-source")
                    finally:
                        read_release.set()
                assert roster._wire.root == new_root
                assert "owner" not in roster._last_snapshot.session_threads.values(), (
                    "A same-named new-wire thread borrowed an old-wire view")
                assert not any(row.target_name == "#shared" for row in roster._row_map.values())

                # A mode can close while the shared owner's asynchronous bind
                # is waiting. It must never acquire (and prune) the shared tree.
                remaining = app.current_mode
                abandoned = (await app.new_session_screen(app.get_main_screen)).mode_name
                await app.switch_mode(remaining)
                bind_entered, bind_release = asyncio.Event(), asyncio.Event()
                bind = roster.bind_wire

                async def slow_bind(service):
                    bind_entered.set()
                    await bind_release.wait()
                    await bind(service)

                with patch.object(roster, "bind_wire", slow_bind):
                    activation = asyncio.ensure_future(app.switch_mode(abandoned))
                    try:
                        await asyncio.wait_for(bind_entered.wait(), 3)
                        await app.close_session_mode(abandoned)
                    finally:
                        bind_release.set()
                    await asyncio.wait_for(activation, 3)
                assert app.current_mode == remaining and bar.screen is app.screen
                assert bar.is_attached and not bar._closed
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("shared Channels: one tree, retained rows/tasks, every new/loading/warm frame, independent right panel")


if __name__ == "__main__":
    asyncio.run(main())
