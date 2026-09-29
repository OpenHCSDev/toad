"""A painted bounded channel page reads its members, never omitted history."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-display-basis-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        for name, tags in (("alice", {"team"}), ("bob", set()), ("carol", set())):
            comms.threads.register(Thread(name, frozenset(tags), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        viewer = comms.messaging.user_identity(str(root)).name
        hidden = comms.messaging.send_message("bob", "carol", "older hidden DM")
        messages = [comms.messaging.send_message("alice", "#team", f"channel {i}") for i in range(12)]
        app = ToadApp(project_dir=str(root))
        # Bound the mounted window too, so automatic edge loading cannot fetch
        # omitted rows and obscure whether the initial page alone was marked.
        with patch("toad.widgets.comms_chat.INITIAL_HISTORY_PAGE_SIZE", 2), patch(
            "toad.widgets.comms_chat.HISTORY_WINDOW_SIZE", 2
        ):
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                owner = app.selected_mode
                await channel_target("#team").open(NavigationContext(app, owner, root, viewer))
                chat = app.screen.query_one(CommsChatView)
                async with asyncio.timeout(5):
                    while comms.views.viewer_snapshot(str(root)).channel_unread["#team"] != 10:
                        await pilot.pause(.02)
                assert chat._has_older
                painted = {seq for source, seq in chat._painted_message_keys() if not source}
                assert painted == {message.seq for message in messages[-2:]}
                seen = comms.bus.reads.seen_sequences(viewer, comms.registry.snapshot())
                assert seen == painted
                assert hidden.seq not in seen
                await app.switch_mode(owner)
                comms.channels.set_channel_any_mode("#team", True)
                comms.channels.update_tags("bob", add=frozenset({"team"}))
                # Expanding a hidden tab's view never manufactures read facts.
                assert comms.views.viewer_snapshot(str(root)).channel_unread["#team"] >= 11
                assert hidden.seq not in comms.bus.reads.seen_sequences(viewer, comms.registry.snapshot())
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("Painted bounded channel page reads exactly its two members; hidden any-mode expansion stays unread")


if __name__ == "__main__":
    asyncio.run(main())
