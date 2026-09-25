"""A preflight rejection restores the exact prompt in the composer."""

import asyncio
import os
import tempfile
from pathlib import Path

from runtime_fixture import ToadApp
from toad.acp.messages import InputFailed


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-input-failure-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            conversation.prompt.text = ""
            conversation.post_message(
                InputFailed("the exact prompt", "Pi native input-ID preflight failed")
            )
            await pilot.pause()
            assert conversation.prompt.text == "the exact prompt"
    print("input failure: exact prompt restored after preflight rejection")


if __name__ == "__main__":
    asyncio.run(main())
