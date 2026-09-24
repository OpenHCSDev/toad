"""Slow local persistence must not delay a user's visible submission."""

import asyncio
import os
import tempfile
from pathlib import Path

from toad.app import ToadApp
from toad.widgets.user_input import UserInput


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-echo-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            gate = asyncio.Event()
            started = asyncio.Event()

            async def slow_append(_text):
                started.set()
                await gate.wait()
                return True

            conversation.prompt_history.append = slow_append
            conversation.prompt.text = "Show this before persistence finishes"
            conversation.prompt.focus()
            sending = asyncio.create_task(pilot.press("enter"))
            await asyncio.wait_for(started.wait(), 2)
            assert any("Show this before" in block.content for block in conversation.query(UserInput))
            assert not gate.is_set()
            gate.set()
            await sending
            await pilot.pause()
    print("local echo: visible before slow persistence or any agent response")


if __name__ == "__main__":
    asyncio.run(main())
