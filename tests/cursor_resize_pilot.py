"""A navigation cursor must never contribute stale height to transcript scrolling."""

import asyncio
import os
import tempfile
from pathlib import Path

from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-cursor-resize-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(70, 25)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            await conversation.contents.remove_children()
            await conversation.post(AgentResponse("\n\n".join("Words that wrap across a narrow terminal. " * 4 for _ in range(30))))
            last = await conversation.post(AgentResponse("Last visible paragraph."))
            await pilot.pause()
            conversation.cursor.follow(last)
            await pilot.pause()
            await pilot.resize_terminal(180, 50)
            await pilot.pause()
            assert conversation.window.virtual_size.height <= conversation.contents.virtual_size.height + 1, (
                conversation.window.virtual_size, conversation.contents.virtual_size,
                conversation.cursor.offset,
            )
    print("cursor resize: overlay cannot create scrollable blank tail")


if __name__ == "__main__":
    asyncio.run(main())
