"""Mounted regression: a Comms Back target belongs to the opening owner."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
from textual.worker import WorkerCancelled

from toad.app import ToadApp
from toad.screens.comms import CommsScreen
from toad.screens.main import MainScreen


async def main() -> None:
    # A separate no-provider root, not the running user's coordination wire.
    root = Path(tempfile.mkdtemp(prefix="toad-owner-nav-"))
    os.environ.update(
        AGENT_COMMS_ROOT=str(root / "wire"),
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_STATE_HOME=str(root / "state"),
        XDG_DATA_HOME=str(root / "data"),
    )
    comms = wire(root / "wire")
    for name in (root.name, "owner-a", "owner-b"):
        comms.threads.register(Thread(name, frozenset(), str(root), process_identity=ProcessIdentity.capture(os.getpid())))

    app = ToadApp(project_dir=str(root))
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        first = app.selected_mode
        view_a = await channel_target("#all").open(NavigationContext(app, first, root, "owner-a"))
        assert isinstance(app.selected_session, CommsScreen)
        assert (app.selected_session.owner_mode, app.selected_session.me) == (first, "owner-a")
        second = (await app.session_navigation.new(lambda: MainScreen(root))).mode_name
        await pilot.pause()
        view_b = await channel_target("#all").open(NavigationContext(app, second, root, "owner-b"))
        assert (
            view_a != view_b
        ), "A second owner must not reuse the first owner's Back view"
        assert isinstance(app.selected_session, CommsScreen)
        assert (app.selected_session.owner_mode, app.selected_session.me) == (second, "owner-b")
        await app.selected_session.action_back_to_agent()
        assert app.selected_mode == second
        app.tab_order.navigate(-1)
        await pilot.pause()
        assert app.selected_mode == view_b
        app.tab_order.navigate(+1)
        await pilot.pause()
        assert app.selected_mode == second
        duplicate = await channel_target("#all").open(NavigationContext(app, second, root, "owner-b"))
        assert duplicate == view_b, (
            duplicate,
            view_b,
            app.open_tabs,
            app.workspace_sessions.require(view_b).owner_mode,
            app.workspace_sessions.require(view_b).kind,
        )
        await app.selected_session.action_back_to_agent()
        assert app.selected_mode == second
        await app.select_session(view_a)
        assert isinstance(app.selected_session, CommsScreen)
        await app.selected_session.action_back_to_agent()
        assert app.selected_mode == first
        comms.registry.rename("owner-a", "owner-renamed")
        app.session_navigation.sync_identity(first, "owner-a", "owner-renamed")
        assert app.workspace_sessions.require(view_a).me == "owner-renamed"
        assert app.workspace_sessions.require(view_b).me == "owner-b"
        assert (
            await channel_target("#all").open(NavigationContext(app, first, root, "owner-a"))
            == view_a
        ), "A late old alias must resolve to the existing renamed view"
        # Closing one owner must close only its own channel; no sibling orphan.
        await app.session_navigation.close(first)
        assert view_a not in app.workspace_sessions.factories
        assert view_b in app.workspace_sessions.factories
        assert app.session_tracker.get_session(second) is not None
        active = app.selected_mode
        assert (
            await channel_target("#all").open(NavigationContext(app, first, root, "owner-a"))
            == active
        ), "A late action from a removed owner must not create a tab"
        assert view_a not in app.workspace_sessions.factories
        replacement = (await app.session_navigation.new(lambda: MainScreen(root))).mode_name
        assert replacement not in (first, second)
        view_reconnected = await channel_target("#all").open(NavigationContext(app, replacement, root, "owner-renamed"))
        assert view_reconnected not in (view_a, view_b)
        await app.selected_session.action_back_to_agent()
        assert app.selected_mode == replacement
        await app.select_session(view_b)
        await app.selected_session.action_back_to_agent()
        assert app.selected_mode == second
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
