"""A displayed channel page clears its own unread rows after every navigation."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp

from toad.widgets.comms_chat import CommsChatView
from toad.widgets.session_tabs import SessionLabel


async def wait_for(pilot, predicate) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await pilot.pause(.05)


async def badge_cleared(app, pilot, mode: str) -> None:
    await wait_for(pilot, lambda: (
        next(tab for tab in app.open_tabs if tab.mode_name == mode).unread == 0
        and "(1)" not in app.screen.query_one(f"SessionLabel#{mode}", SessionLabel).render().plain
    ))


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-unread-navigation-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        comms = wire(root / "wire")
        comms.register(Thread("sender", frozenset(), str(root)))
        viewer = comms.user_identity(str(root))
        comms.send("sender", "#all", "first-pending")
        app = ToadApp(project_dir=str(root))

        def unread() -> int:
            return comms.viewer_snapshot(str(root)).channel_unread["#all"]

        assert unread() == 1
        async with app.run_test(size=(110, 36)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            name = app.screen._comms_thread
            mode = await app.open_comms_session(owner_mode=owner, project_path=root,
                                               me=name, target="#all", kind="channel")
            chat = app.screen.query_one(CommsChatView)
            await wait_for(pilot, lambda: chat._history_initialized)
            assert any(item.body == "first-pending" for item, _ in chat._history)
            await wait_for(pilot, lambda: unread() == 0)
            await badge_cleared(app, pilot, mode)
            await app.switch_mode(owner)
            comms.send("sender", "#all", "second-pending")
            assert unread() == 1
            await app.switch_mode(mode)
            chat = app.screen.query_one(CommsChatView)
            await wait_for(pilot, lambda: any(
                item.body == "second-pending" for item, _ in chat._history
            ))
            await wait_for(pilot, lambda: unread() == 0)
            await badge_cleared(app, pilot, mode)
            await app.switch_mode(owner)
            comms.send("sender", viewer.name, "dm-pending")

            def dm_unread() -> int:
                return comms.viewer_snapshot(str(root)).unread.get("sender", 0)

            assert dm_unread() == 1
            dm_mode = await app.open_comms_session(owner_mode=owner, project_path=root,
                                                   me=viewer.name, target="sender", kind="dm")
            dm = app.screen.query_one(CommsChatView)
            await wait_for(pilot, lambda: any(
                item.body == "dm-pending" for item, _ in dm._history
            ))
            await wait_for(pilot, lambda: dm_unread() == 0)
            await badge_cleared(app, pilot, dm_mode)
            await app.switch_mode(owner)
            comms.send("sender", "#all", "aggregate-pending")

            def aggregate_unread() -> int:
                return comms.viewer_snapshot(str(root)).channel_unread.get("#any", 0)

            assert aggregate_unread() >= 1
            aggregate_mode = await app.open_comms_session(owner_mode=owner, project_path=root,
                                                          me=viewer.name, target="#any", kind="irc")
            aggregate = app.screen.query_one(CommsChatView)
            await wait_for(pilot, lambda: any(
                item.body == "aggregate-pending" for item, _ in aggregate._history
            ))
            await wait_for(pilot, lambda: aggregate_unread() == 0)
            await badge_cleared(app, pilot, aggregate_mode)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("painted channel/DM/#any unread clears on navigation and existing-tab return")


if __name__ == "__main__":
    asyncio.run(main())
