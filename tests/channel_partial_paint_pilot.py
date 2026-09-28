"""Partial viewport ACKs retain pending evidence for rows reached by scrolling."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-partial-paint-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        comms.register(Thread("peer", frozenset({"team"}), str(root), pid=os.getpid()))
        viewer = comms.user_identity(str(root)).name
        rows = [comms.send_message("peer", "#team", f"row {i}\n" + "body\n" * 10) for i in range(8)]
        acknowledged = set()
        original_mark = CommsChatView._mark_painted_page

        async def checked_mark(chat, page, original_page=None):
            selected = {message.seq for message in page.messages}
            assert selected <= set(chat._painted_message_sequences())
            assert page.display_scope is not None and page.display_scope.displayed is not None
            assert selected == {
                seq for item in page.display_scope.displayed.conversations for seq in item.sequences
            }
            acknowledged.update(selected)
            await original_mark(chat, page, original_page)

        app = ToadApp(project_dir=str(root))
        with patch.object(CommsChatView, "_mark_painted_page", checked_mark):
            async with app.run_test(size=(90, 24)) as pilot:
                await pilot.pause()
                await app.open_comms_session(
                    owner_mode=app.current_mode, project_path=root, me=viewer,
                    target="#team", kind="channel",
                )
                chat = app.screen.query_one(CommsChatView)
                async with asyncio.timeout(5):
                    while not acknowledged or chat._ack_inflight:
                        await pilot.pause(.02)
                seen = comms.reads.seen_sequences(viewer, comms.registry.snapshot())
                assert 0 < len(seen) < len(rows)
                assert seen == acknowledged
                # Revisit every mounted body. Rows from the original page stay
                # pending even though its first subset has already been ACKed.
                for message, widget in list(chat._history):
                    if message.seq in seen:
                        continue
                    body = widget.read_ack_widget()
                    chat.window.scroll_to(
                        y=chat.window.scroll_y + body.region.y - chat.window.content_region.y,
                        animate=False, immediate=True,
                    )
                    async with asyncio.timeout(5):
                        while message.seq not in comms.reads.seen_sequences(viewer, comms.registry.snapshot()):
                            await pilot.pause(.02)
                assert comms.reads.seen_sequences(viewer, comms.registry.snapshot()) == {row.seq for row in rows}
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("Partial viewport ACKs contain only painted bodies; scrolling acknowledges the remaining captured rows")


if __name__ == "__main__":
    asyncio.run(main())
