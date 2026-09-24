"""Blocked route metadata must not hold typing, steal focus, or reopen owners."""

import asyncio
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from agent_comms import Thread, wire

from runtime_fixture import ToadApp
from toad.navigation_preparation import (
    CommsNavigationRequest, NavigationReader, NavigationRequest, ThreadNavigationRequest,
)


class GateRequest(NavigationRequest[str]):
    def __init__(self, name: str, *, fail: bool = False):
        self.name = name
        self.fail = fail
        self.entered = threading.Event()
        self.release = threading.Event()

    def read(self) -> str:
        self.entered.set()
        if not self.release.wait(8):
            raise TimeoutError("metadata gate was not released")
        if self.fail:
            raise ValueError("obsolete read failed")
        return self.name


async def admission() -> None:
    reader = NavigationReader()
    requests = [GateRequest(str(index), fail=index == 1) for index in range(4)]
    tasks = []
    try:
        for request in requests[:2]:
            tasks.append(asyncio.create_task(reader.read(request)))
            assert await asyncio.to_thread(request.entered.wait, 2)
        tasks[0].cancel()
        await asyncio.gather(tasks[0], return_exceptions=True)
        for request in requests[2:]:
            tasks.append(asyncio.create_task(reader.read(request)))
            await asyncio.sleep(0)
        assert not requests[2].entered.is_set() and not requests[3].entered.is_set()
        requests[0].release.set()
        assert await asyncio.to_thread(requests[3].entered.wait, 2)
        assert not requests[2].entered.is_set(), "Superseded queue entry performed IO"
        requests[1].release.set()
        requests[3].release.set()
        assert await asyncio.gather(*tasks[1:]) == [None, None, "3"]
        closing_request = GateRequest("closing")
        requests.append(closing_request)
        tasks.append(asyncio.create_task(reader.read(closing_request)))
        assert await asyncio.to_thread(closing_request.entered.wait, 2)
        closing = asyncio.create_task(reader.aclose())
        await asyncio.sleep(0)
        assert not closing.done(), "Shutdown lost track of a real metadata read"
        closing_request.release.set()
        await closing
        assert await tasks[-1] is None
    finally:
        for request in requests:
            request.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await reader.aclose()


async def mounted() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-route-read-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        comms.register(Thread("metadata-peer", frozenset(), str(root), pid=os.getpid()))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            source = app.screen
            other = (await app.new_session_screen(app.get_main_screen)).mode_name
            for request_type, kind in ((ThreadNavigationRequest, "thread"), (CommsNavigationRequest, "channel")):
                await app.switch_mode(owner)
                await pilot.pause()
                entered, release = threading.Event(), threading.Event()
                original = request_type.read
                thread_ids = []

                def gated(request):
                    thread_ids.append(threading.get_ident())
                    entered.set()
                    if not release.wait(8):
                        raise TimeoutError("route read gate was not released")
                    return original(request)

                opening = None
                try:
                    with patch.object(request_type, "read", gated):
                        opening = asyncio.create_task(app.open_comms_session(
                            owner_mode=owner, project_path=root, me=source._comms_thread,
                            target="metadata-peer" if kind == "thread" else "#all", kind=kind,
                        ))
                        assert await asyncio.to_thread(entered.wait, 2)
                        assert thread_ids == [thread_ids[0]] and thread_ids[0] != threading.get_ident()
                        source.conversation.prompt.focus()
                        await pilot.press("k", "e", "e", "p")
                        assert source.conversation.prompt.text.endswith("keep")
                        await asyncio.wait_for(app.switch_mode(other), 2)
                        assert not release.is_set() and not opening.done()
                        release.set()
                        assert await asyncio.wait_for(opening, 2) == other
                        assert app.current_mode == other, "Old route metadata stole focus"
                        assert not app._comms_modes, "Superseded route created an unused tab"
                finally:
                    release.set()
                    if opening is not None:
                        await asyncio.gather(opening, return_exceptions=True)

            # Canonical aliases must reuse open threads even before their UI
            # receives the asynchronous coordination rename notification.
            existing = app._main_session_screen(other)
            existing._coordination_root = str(root / "wire")
            existing._comms_thread = "metadata-peer"
            comms.registry.rename("metadata-peer", "metadata-renamed")
            reused = await app.open_thread_session(
                owner_mode=owner, project_path=root, target="metadata-peer",
            )
            assert reused == other and app.session_tracker.session_count == 2

            # Complete a channel read only after its inactive owner has closed.
            entered, release = threading.Event(), threading.Event()
            original = CommsNavigationRequest.read

            def after_close(request):
                entered.set()
                if not release.wait(8):
                    raise TimeoutError("owner close gate was not released")
                return original(request)

            opening = None
            try:
                with patch.object(CommsNavigationRequest, "read", after_close):
                    opening = asyncio.create_task(app.open_comms_session(
                        owner_mode=owner, project_path=root, me=source._comms_thread,
                        target="#all", kind="channel",
                    ))
                    assert await asyncio.to_thread(entered.wait, 2)
                    await asyncio.wait_for(app.close_session_mode(owner), 2)
                    release.set()
                    assert await asyncio.wait_for(opening, 2) == other
                    assert owner not in app._screen_stacks and not app._comms_modes
            finally:
                release.set()
                if opening is not None:
                    await asyncio.gather(opening, return_exceptions=True)


async def main():
    await admission()
    await mounted()
    print("navigation metadata: off-loop reads, typing, latest intent, closed owner, bounded cancellation and drainage OK")


if __name__ == "__main__":
    asyncio.run(main())
