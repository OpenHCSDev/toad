"""Mounted regression: a Comms Back target belongs to the opening owner."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from textual.worker import WorkerCancelled

from toad.app import ToadApp
from toad.screens.comms import CommsScreen
from toad.screens.main import MainScreen


async def main() -> None:
    # A separate no-provider root, not the running user's coordination wire.
    root = Path(tempfile.mkdtemp(prefix="toad-owner-nav-", dir="/dev/shm"))
    os.environ.update(
        AGENT_COMMS_ROOT=str(root / "wire"),
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_STATE_HOME=str(root / "state"),
        XDG_DATA_HOME=str(root / "data"),
    )
    comms = wire(root / "wire")
    for name in (root.name, "owner-a", "owner-b"):
        comms.register(Thread(name, frozenset(), str(root), pid=os.getpid()))

    app = ToadApp(project_dir=str(root))
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        first = app.current_mode
        view_a = await app.open_comms_session(
            owner_mode=first,
            project_path=root,
            me="owner-a",
            target="#all",
            kind="channel",
        )
        assert isinstance(app.screen, CommsScreen)
        assert (app.screen.owner_mode, app.screen.me) == (first, "owner-a")
        second = (await app.new_session_screen(lambda: MainScreen(root))).mode_name
        await pilot.pause()
        view_b = await app.open_comms_session(
            owner_mode=second,
            project_path=root,
            me="owner-b",
            target="#all",
            kind="channel",
        )
        assert (
            view_a != view_b
        ), "A second owner must not reuse the first owner's Back view"
        assert isinstance(app.screen, CommsScreen)
        assert (app.screen.owner_mode, app.screen.me) == (second, "owner-b")
        await app.screen.action_back_to_agent()
        assert app.current_mode == second
        app.navigate_tab_history(-1)
        await pilot.pause()
        assert app.current_mode == view_b
        app.navigate_tab_history(+1)
        await pilot.pause()
        assert app.current_mode == second
        duplicate = await app.open_comms_session(
            owner_mode=second,
            project_path=root,
            me="owner-b",
            target="#all",
            kind="channel",
        )
        assert duplicate == view_b, (
            duplicate,
            view_b,
            list(app._comms_modes.items()),
            app.get_screen_stack(view_b)[0].owner_mode,
            app.get_screen_stack(view_b)[0].kind,
        )
        await app.screen.action_back_to_agent()
        assert app.current_mode == second
        await app.switch_mode(view_a)
        assert isinstance(app.screen, CommsScreen)
        await app.screen.action_back_to_agent()
        assert app.current_mode == first
        comms.registry.rename("owner-a", "owner-renamed")
        app.sync_coordination_identity(first, "owner-a", "owner-renamed")
        assert app.get_screen_stack(view_a)[0].me == "owner-renamed"
        assert app.get_screen_stack(view_b)[0].me == "owner-b"
        assert (
            await app.open_comms_session(
                owner_mode=first,
                project_path=root,
                me="owner-a",
                target="#all",
                kind="channel",
            )
            == view_a
        ), "A late old alias must resolve to the existing renamed view"
        # Closing one owner must close only its own channel; no sibling orphan.
        await app.close_session_mode(first)
        assert view_a not in app._screen_stacks
        assert view_b in app._screen_stacks
        assert app.session_tracker.get_session(second) is not None
        active = app.current_mode
        assert (
            await app.open_comms_session(
                owner_mode=first,
                project_path=root,
                me="owner-a",
                target="#all",
                kind="channel",
            )
            == active
        ), "A late action from a removed owner must not create a tab"
        assert not any(key.owner_mode == first for key in app._comms_modes)
        replacement = (await app.new_session_screen(lambda: MainScreen(root))).mode_name
        assert replacement not in (first, second)
        view_reconnected = await app.open_comms_session(
            owner_mode=replacement,
            project_path=root,
            me="owner-renamed",
            target="#all",
            kind="channel",
        )
        assert view_reconnected not in (view_a, view_b)
        await app.screen.action_back_to_agent()
        assert app.current_mode == replacement
        await app.switch_mode(view_b)
        await app.screen.action_back_to_agent()
        assert app.current_mode == second
        # A poll started just before teardown must not race the disappearing
        # Textual screen stack and turn this focused navigation test flaky.
        app.workers.cancel_all()
        stopped = await asyncio.gather(
            *(worker.wait() for worker in tuple(app.workers)), return_exceptions=True
        )
        assert all(
            not isinstance(result, BaseException) or isinstance(result, WorkerCancelled)
            for result in stopped
        ), stopped
    print(
        "mounted two-owner Back, same-owner reuse, stale owner and close isolation OK"
    )


if __name__ == "__main__":
    asyncio.run(main())
