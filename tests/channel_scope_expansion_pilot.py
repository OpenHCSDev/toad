"""A mounted any-mode channel must reveal older messages entering its scope."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
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
            comms.registry.declare(Thread(name, tags, str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        viewer = comms.messaging.user_identity(str(root)).name
        comms.messaging.send("carol", "dave", "older newly visible DM")
        comms.messaging.send("alice", "#team", "current channel message")
        comms.channels.set_channel_any_mode("#team", True)
        assert [m.body for m in comms.views.channel_display_page("#team", worktree=str(root)).messages] == [
            "current channel message"
        ]

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await channel_target("#team").open(NavigationContext(app, app.selected_mode, root, viewer))
            chat = app.screen.query_one(CommsChatView)
            await chat._refresh()
            await pilot.pause()
            assert [m.body for m, _ in chat.message_history.rows] == ["current channel message"]
            assert not chat.message_history.has_older

            comms.channels.update_tags("carol", add=frozenset({"team"}))
            expanded = comms.views.channel_display_page("#team", worktree=str(root))
            assert [m.body for m in expanded.messages][:2] == [
                "older newly visible DM", "current channel message"
            ]
            await chat._refresh()
            await pilot.pause()
            assert [m.body for m, _ in chat.message_history.rows][:2] == [
                "older newly visible DM", "current channel message"
            ]
        await asyncio.get_running_loop().shutdown_default_executor()
    print("mounted any-mode scope expansion reveals older history")


if __name__ == "__main__":
    asyncio.run(main())
