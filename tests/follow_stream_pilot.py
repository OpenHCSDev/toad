"""Follow live output at the tail, release while reading, and resume at the tail."""

import asyncio
import os
import tempfile
from pathlib import Path

from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-follow-stream-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            response = await conversation.post(AgentResponse("\n\n".join(f"Paragraph {i}" for i in range(40))))
            window = conversation.window
            window.anchor(False)
            conversation.refresh_block_cursor()
            assert window.follows_tail, "Returning the block cursor to the composer disabled follow"
            window.anchor()
            await pilot.pause()
            await response.append("\n\nNew output at the tail.")
            await pilot.pause()
            assert window.follows_tail and window.scroll_y == window.max_scroll_y
            window.scroll_relative(y=-8, animate=False, immediate=True)
            await pilot.pause()
            position = window.scroll_y
            await response.append("\n\nOutput while reading older text.")
            await pilot.pause()
            assert not window.follows_tail and window.scroll_y == position
            window.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            assert window.follows_tail
            for width, height in ((145, 40), (70, 25), (100, 30)):
                await pilot.resize_terminal(width, height)
                await response.append("\n\nFurther live output after resize.")
                await pilot.pause()
                assert window.follows_tail and window.scroll_y == window.max_scroll_y
    print("follow stream: automatic tail, release on scroll-up, resume at bottom, resize preserved")


if __name__ == "__main__":
    asyncio.run(main())
