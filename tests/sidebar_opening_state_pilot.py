"""Channels state must remain visible on every loading and destination frame."""

import asyncio
import os
from pathlib import Path
import tempfile
from threading import Event
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad import __file__ as toad_file
from toad.acp.agent import Agent
from toad.agent import AgentReady
from toad.navigation_preparation import ThreadNavigationRequest
from toad.screens.comms import CommsScreen
from toad.screens.pending_thread import PendingThreadScreen
from toad.widgets.comms_chat import session_thread_name
from toad.widgets.side_bar import SideBar


class FrameApp(ToadApp):
    CSS_PATH = Path(toad_file).parent / "toad.tcss"
    frames = None

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if self.frames is not None and renderable is not None and not self._batch_count and screen is self.screen:
            bar = screen.query_one_optional("#channels-sidebar", SideBar)
            self.frames.append(None if bar is None else (
                bar.collapsed, bar.region.x, bar.size.width,
                bar.query_one("#sidebar-panels").display,
            ))


async def until(condition):
    async with asyncio.timeout(8):
        while not condition():
            await asyncio.sleep(.01)


def check_frames(app, collapsed, x, width):
    assert app.frames, "No presented frame observed"
    assert all(frame == (collapsed, x, width, not collapsed) for frame in app.frames), app.frames


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-sidebar-opening-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        me = session_thread_name(root)
        comms.register(Thread(me, frozenset({"fixture"}), str(root), pid=os.getpid()))
        for name in ("open-peer", "closed-peer"):
            comms.register(Thread(name, frozenset(), str(root), pid=os.getpid()))

        async def start(agent, target):
            agent._message_target = target
            agent._task = asyncio.create_task(asyncio.sleep(0))
            target.post_message(AgentReady())

        app = FrameApp(project_dir=str(root))
        with patch.object(Agent, "start", start):
            async with app.run_test(size=(110, 37)) as pilot:
                await pilot.pause()
                await until(lambda: app._sidebar_snapshot is not None)
                owner = app.current_mode
                app.screen._agent = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                     "run_command": {"*": "/bin/false"}, "protocol": "acp"}
                # Include the same-edge placement case: a loading screen must
                # reserve the other collapsed sidebar's place in that model.
                app.sidebar_layout.move("thread-sidebar", "left")
                app.sidebar_layout.swap("channels-sidebar")
                app.sidebar_layout_changed.publish(None)
                await pilot.pause()
                for collapsed, peer in ((False, "open-peer"), (True, "closed-peer")):
                    app.frames = None
                    await app.switch_mode(owner)
                    app.settings.set("sidebar.hide", collapsed)
                    await pilot.pause()
                    bar = app.screen.query_one("#channels-sidebar", SideBar)
                    x, width = bar.region.x, bar.size.width
                    entered, release = Event(), Event()
                    original = ThreadNavigationRequest.read

                    def gated(request):
                        entered.set()
                        if not release.wait(8):
                            raise TimeoutError("Route gate was not released")
                        return original(request)

                    opening = None
                    try:
                        with patch.object(ThreadNavigationRequest, "read", gated):
                            app.frames = []
                            opening = asyncio.create_task(app.open_thread_session(
                                owner_mode=owner, project_path=root, target=peer))
                            assert await asyncio.to_thread(entered.wait, 3)
                            assert isinstance(app.screen, PendingThreadScreen)
                            await pilot.pause()
                            check_frames(app, collapsed, x, width)
                            app.frames = None
                            await pilot.resize_terminal(110 if collapsed else 96, 37)
                            await pilot.pause()
                            bar = app.screen.query_one("#channels-sidebar", SideBar)
                            expected = app.sidebar_layout.resolve(app.size.width, {
                                "channels-sidebar": collapsed, "thread-sidebar": True,
                            }).bars["channels-sidebar"]
                            x, width = bar.region.x, bar.size.width
                            assert (x, width) == (expected.x, expected.width)
                            app.frames = []
                            release.set()
                            await asyncio.wait_for(opening, 8)
                            await pilot.pause()
                            check_frames(app, collapsed, x, width)
                    finally:
                        release.set()
                        if opening is not None:
                            await asyncio.gather(opening, return_exceptions=True)

                for collapsed in (False, True):
                    app.frames = None
                    await app.switch_mode(owner)
                    app.settings.set("sidebar.hide", collapsed)
                    await pilot.pause()
                    bar = app.screen.query_one("#channels-sidebar", SideBar)
                    x, width = bar.region.x, bar.size.width
                    target = f"#opening-{int(collapsed)}"
                    comms.set_channel(target, frozenset({"fixture"}))
                    comms.send(me, target, "Displayed only after hydration")
                    blocked = asyncio.Event()
                    original_start = CommsScreen._start_hydration

                    def hold_hydration(screen):
                        blocked.set()

                    with patch.object(CommsScreen, "_start_hydration", hold_hydration):
                        app.frames = []
                        opening = asyncio.create_task(app.open_comms_session(
                            owner_mode=owner, project_path=root, me=me, target=target, kind="channel"))
                        try:
                            await asyncio.wait_for(blocked.wait(), 4)
                            await pilot.pause()
                            assert isinstance(app.screen, CommsScreen)
                            check_frames(app, collapsed, x, width)
                            retained = app.screen.query_one("#channels-sidebar", SideBar)
                            assert not app.screen._content_loaded
                            assert comms.viewer_snapshot(str(root)).channel_unread[target] == 1
                            # Controls remain usable while history is gated;
                            # hydration must keep the latest intent too.
                            app.frames = None
                            retained.toggle()
                            await pilot.pause()
                            expected_collapsed = not collapsed
                            assert retained.collapsed == expected_collapsed
                            x, width = retained.region.x, retained.size.width
                            app.frames = []
                            original_start(app.screen)
                            await asyncio.wait_for(opening, 8)
                            await pilot.pause()
                            assert app.screen.query_one("#channels-sidebar", SideBar) is retained
                            check_frames(app, expected_collapsed, x, width)
                        finally:
                            if not opening.done():
                                original_start(app.screen)
                            await asyncio.gather(opening, return_exceptions=True)
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("sidebar opening: open/closed geometry retained on every pending/hydration frame; same-edge placement, native controls and read boundary OK")


if __name__ == "__main__":
    asyncio.run(main())
