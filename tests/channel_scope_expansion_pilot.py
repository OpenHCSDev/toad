"""A mounted any-mode channel must reveal older messages entering its scope."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-scope-expansion-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        for name, tags in (
            ("alice", frozenset({"team"})),
            ("bob", frozenset()),
            ("carol", frozenset()),
            ("dave", frozenset()),
        ):
            comms.register(Thread(name, tags, str(root), pid=os.getpid()))
        viewer = comms.user_identity(str(root)).name
        comms.send("carol", "dave", "older newly visible DM")
        comms.send("alice", "#team", "current channel message")
        comms.set_channel_any_mode("#team", True)
        assert [m.body for m in comms.channel_display_page("#team", worktree=str(root)).messages] == [
            "current channel message"
        ]

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app.open_comms_session(
                owner_mode=app.current_mode,
                project_path=root,
                me=viewer,
                target="#team",
                kind="channel",
            )
            chat = app.screen.query_one(CommsChatView)
            await chat._refresh()
            await pilot.pause()
            assert [m.body for m, _ in chat._history] == ["current channel message"]
            assert not chat._has_older

            comms.update_tags("carol", add=frozenset({"team"}))
            expanded = comms.channel_display_page("#team", worktree=str(root))
            assert [m.body for m in expanded.messages][:2] == [
                "older newly visible DM", "current channel message"
            ]
            await chat._refresh()
            await pilot.pause()
            assert [m.body for m, _ in chat._history][:2] == [
                "older newly visible DM", "current channel message"
            ]
        await asyncio.get_running_loop().shutdown_default_executor()
    print("mounted any-mode scope expansion reveals older history")


if __name__ == "__main__":
    asyncio.run(main())
