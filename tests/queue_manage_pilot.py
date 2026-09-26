"""Remote edits are held without exact-ID/CAS support; never clear-and-resend."""

import asyncio
import os
import tempfile
from pathlib import Path

from textual.content import Content

from runtime_fixture import ToadApp


class FakeAgent:
    def __init__(self):
        self.cleared = 0
        self.sent: list[tuple[str, str]] = []

    def get_info(self):
        return Content("Fake agent")

    async def stop(self):
        pass

    async def cancel(self):
        raise AssertionError("editing the queue must not cancel the turn")

    async def clear_queue(self):
        self.cleared += 1

    async def send_prompt(self, prompt, *, delivery="queue", defer_display=False):
        self.sent.append((prompt, delivery))
        return None


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-queue-manage-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            agent = FakeAgent()
            conversation.set_reactive(type(conversation).agent, agent)
            conversation.agent_ready = True
            conversation.turn = "agent"
            conversation.queue_supported = True
            conversation.queued_prompts = ["same", "same", "unknown input"]
            conversation.prompt.text = "local unsent draft"
            await pilot.pause()

            def unchanged():
                assert conversation.queued_prompts == ["same", "same", "unknown input"]
                assert conversation.prompt.text == "local unsent draft"
                assert agent.cleared == 0 and agent.sent == []
                assert conversation.turn == "agent"

            screen = app.screen
            conversation.open_queue_menu()
            await pilot.pause()
            assert app.screen is screen, "Unsupported remote edit menu was exposed"
            unchanged()
            for action in ("remove:1", "edit:0", "clear", None):
                conversation._on_queue_choice(action)
                await pilot.pause()
                unchanged()
            for replacement in ([], ["same"], ["same", "same", "unknown input"]):
                conversation.replace_queued(replacement)
                await pilot.pause()
                unchanged()
            # Holding remote controls must not prevent ordinary local editing.
            conversation.prompt.text = "revised local draft"
            assert conversation.prompt.text == "revised local draft"
            assert agent.cleared == 0 and agent.sent == []
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("queue manage: unsupported remote mutations held, no clear/resend, local draft untouched")


if __name__ == "__main__":
    asyncio.run(main())