"""Thread tab and loading frame appear before authoritative route IO finishes."""

import asyncio
import os
from pathlib import Path
import tempfile
from threading import Event
from unittest.mock import patch

from agent_comms import Thread, wire

from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.agent import AgentReady
from toad.navigation_preparation import ThreadNavigationRequest
from toad.screens.main import MainScreen
from toad.screens.pending_thread import PendingThreadScreen
from toad.widgets.conversation import ThreadLoading


class FrameApp(ToadApp):
    def __init__(self, **kwargs):
        self.loading_frames = 0
        super().__init__(**kwargs)

    def _display(self, screen, renderable):
        result = super()._display(screen, renderable)
        if (isinstance(screen, PendingThreadScreen) and screen is self.screen
                and renderable is not None and not self._batch_count):
            self.loading_frames += 1
        return result


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-pending-thread-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        for name in ("first-peer", "close-peer"):
            comms.register(Thread(name, frozenset(), str(root), pid=os.getpid()))

        async def fake_start(agent, target):
            agent._message_target = target
            agent._task = asyncio.create_task(asyncio.sleep(0))
            target.post_message(AgentReady())

        app = FrameApp(project_dir=str(root))
        with patch.object(Agent, "start", fake_start):
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                owner = app.current_mode
                owner_screen = app.screen
                owner_screen._agent = {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                                       "run_command": {"*": "/bin/false"}, "protocol": "acp"}
                original = ThreadNavigationRequest.read

                async def blocked_open(target):
                    entered, release = Event(), Event()

                    def gated(request):
                        entered.set()
                        if not release.wait(8):
                            raise TimeoutError("Metadata gate not released")
                        return original(request)

                    mocked = patch.object(ThreadNavigationRequest, "read", gated)
                    mocked.start()
                    opening = asyncio.create_task(app.open_thread_session(
                        owner_mode=owner, project_path=root, target=target))
                    assert await asyncio.to_thread(entered.wait, 2)
                    assert isinstance(app.screen, PendingThreadScreen)
                    pending = app.current_mode
                    await pilot.pause()
                    assert app.loading_frames > 0, "Route IO began before the tab drew a loading frame"
                    frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                    assert "Loading new thread and history" in frame
                    assert any(tab.mode_name == pending and tab.title == f"⌛ @{target}"
                               for tab in app.open_tabs)
                    assert app.screen.query_one(ThreadLoading).is_mounted
                    assert not release.is_set() and not opening.done()
                    return opening, pending, release, mocked

                opening, pending, release, mocked = await blocked_open("first-peer")
                try:
                    await app.switch_mode(pending)
                    assert not opening.done(), "Selecting the current loading tab cancelled its read"
                    duplicate = asyncio.create_task(app.open_thread_session(
                        owner_mode=owner, project_path=root, target="first-peer"))
                    await asyncio.sleep(0)
                    assert not duplicate.done() and len(app._pending_thread_modes) == 1
                    release.set()
                    first = await asyncio.wait_for(opening, 8)
                    assert await asyncio.wait_for(duplicate, 8) == first
                    assert first != pending and app.current_mode == first
                    assert isinstance(app.screen, MainScreen)
                    assert not app._pending_thread_modes
                    assert all(tab.mode_name != pending for tab in app.open_tabs)
                    assert app.session_tracker.session_count == 2
                finally:
                    release.set()
                    mocked.stop()

                await app.switch_mode(owner)
                opening, pending, release, mocked = await blocked_open("close-peer")
                try:
                    await asyncio.wait_for(app.close_session_mode(pending), 3)
                    assert app.current_mode == owner
                    owner_screen.conversation.prompt.focus()
                    await pilot.press("k", "e", "e", "p")
                    assert owner_screen.conversation.prompt.text.endswith("keep")
                    release.set()
                    assert await asyncio.wait_for(opening, 3) == owner
                    assert all(tab.mode_name != pending for tab in app.open_tabs)
                    assert app.session_tracker.session_count == 2
                finally:
                    release.set()
                    mocked.stop()
                invalid = await app.open_thread_session(owner_mode=owner, project_path=root, target="missing")
                assert invalid == owner and app.current_mode == owner
                assert not app._pending_thread_modes

                # A closing owner must not strand a provisional destination or
                # return a deleted mode after an already-running reader finishes.
                opening, pending, release, mocked = await blocked_open("close-peer")
                try:
                    await asyncio.wait_for(app.close_session_mode(owner), 4)
                    assert app.session_tracker.get_session(owner) is None
                    release.set()
                    result = await asyncio.wait_for(opening, 4)
                    assert result == app.current_mode and result != owner
                    assert not app._pending_thread_modes
                finally:
                    release.set()
                    mocked.stop()
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("pending thread: mounted/loading frame before gated metadata; duplicate, close, stale result and invalid route safe")


if __name__ == "__main__":
    asyncio.run(main())
