from toad.mounted_message_history import MountedMessageHistory
"""A visible divider cannot acknowledge a message whose body is below the viewport."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.irc_message import IRCMessageText
from toad.widgets.message_divider import MessageDivider


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-divider-ack-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        comms.registry.declare(Thread("peer", frozenset({"team"}), str(root)))
        for index in range(7):
            comms.messaging.send("peer", "#team", f"earlier {index} " + "body " * 20)
        comms.views.mark_user_view_read("#team", worktree=str(root))
        last = comms.messaging.send_message("peer", "#team", "LAST " + "body " * 250)

        app = ToadApp(project_dir=str(root))
        # Hold automatic ACKs while arranging the divider-only viewport.
        # Initial tail paint may legitimately acknowledge the body with S4.
        mark_visible = MountedMessageHistory.mark_visible
        with patch.object(MountedMessageHistory, "mark_visible"):
            async with app.run_test(size=(80, 22)) as pilot:
                await pilot.pause()
                await channel_target("#team").open(NavigationContext(app, app.selected_mode, root, "peer"))
                chat = app.screen.query_one(CommsChatView)
                async with asyncio.timeout(5):
                    while not chat.message_history.initialized:
                        await pilot.pause(.02)
                block = next(widget for message, widget in chat.message_history.rows if message.seq == last.seq)
                divider = block.query_one(MessageDivider)
                body = block.query_one(IRCMessageText)
                await pilot.pause()
                viewport = chat.window.content_region
                chat.window.scroll_to(
                    y=chat.window.scroll_y + divider.region.bottom - viewport.bottom,
                    animate=False, immediate=True,
                )
                await pilot.pause()
                assert divider.region.overlaps(chat.window.content_region)
                assert not body.region.overlaps(chat.window.content_region)
                assert last.seq not in {seq for source, seq in chat.message_history.painted_keys() if not source}

                page = chat.message_history.read_page(comms, after=last.seq - 1)
                chat.message_history.channel_receipts[last.seq] = page
                mark_visible(chat)
                await pilot.pause(.2)
                assert comms.views.viewer_snapshot(str(root)).channel_unread["#team"] == 1
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("divider-only viewport leaves the unpainted message unread")


if __name__ == "__main__":
    asyncio.run(main())
