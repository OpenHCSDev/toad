"""Initial source callbacks wait for presentation and cannot outlive their view."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.agent import AgentReady
from toad.screens.session_view import SessionView
from toad.widgets.conversation import ThreadLoading


async def until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(.01)


async def main():
    with TemporaryDirectory(prefix="toad-first-frame-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        for name in ("visible-peer", "closed-peer"):
            comms.register(Thread(name, frozenset(), str(root), pid=os.getpid()))
        started, written = [], set()
        finish_frame = SessionView._finish_first_frame

        def hold_frame(screen):
            written.add(screen)

        async def start(agent, target):
            assert target.screen._first_frame_presented
            started.append(target.screen._comms_thread)
            agent._message_target = target
            agent._task = asyncio.create_task(asyncio.sleep(0))
            target.post_message(AgentReady())

        app = ToadApp(project_dir=str(root))
        with patch.object(SessionView, "_finish_first_frame", hold_frame), patch.object(Agent, "start", start):
            async with app.run_test(size=(100, 35)) as pilot:
                await pilot.pause()
                owner = app.current_mode
                owner_screen = app.screen
                assert owner_screen in written
                assert app._sidebar_snapshot is None, "Initial sidebar read escaped presentation gate"
                finish_frame(owner_screen)
                await until(lambda: app._sidebar_snapshot is not None)
                owner_screen._agent = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                       "run_command": {"*": "/bin/false"}, "protocol": "acp"}
                mode = await app.open_thread_session(owner_mode=owner, project_path=root, target="visible-peer")
                await pilot.pause()
                view = app.screen
                assert view.id == mode and view in written
                assert view.query_one(ThreadLoading).is_mounted and not started
                finish_frame(view)
                await until(lambda: started == ["visible-peer"])
                finish_frame(view)
                await pilot.pause()
                assert started == ["visible-peer"], "A second flush restarted the agent"

                await app.switch_mode(owner)
                closing = await app.open_thread_session(owner_mode=owner, project_path=root, target="closed-peer")
                await pilot.pause()
                closed_view = app.screen
                assert closed_view in written and not closed_view._first_frame_presented
                await app.close_session_mode(closing)
                assert not closed_view._initial_frame_callbacks
                finish_frame(closed_view)
                await pilot.pause()
                assert started == ["visible-peer"], "Closed view started a deferred agent"
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("first frame: sidebar/agent startup gated, callbacks delivered once, closed views cannot start")


if __name__ == "__main__":
    asyncio.run(main())
