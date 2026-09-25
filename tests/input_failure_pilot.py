"""A preflight rejection restores the exact prompt in the composer."""

import asyncio
import os
import tempfile
from pathlib import Path

from runtime_fixture import ToadApp
from toad.acp.messages import InputFailed
from toad.widgets.conversation import Conversation


class FailingAgent:
    uses_turn_events = False

    async def send_prompt(self, prompt, **kwargs):
        raise FileNotFoundError(2, "agent socket disappeared")

    async def stop(self):
        pass


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
            conversation.set_reactive(Conversation.agent, FailingAgent())
            conversation.prompt.text = ""
            conversation.send_prompt_to_agent("the local failure prompt", immediate=True)
            await pilot.pause()
            assert conversation.prompt.text == "the local failure prompt"
    print("input failure: exact prompt restored after preflight rejection")


if __name__ == "__main__":
    asyncio.run(main())
