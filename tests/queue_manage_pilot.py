"""Queued prompts can be edited or removed without stopping the turn."""

import asyncio
import os
import tempfile
from pathlib import Path

from textual.content import Content

from toad.app import ToadApp


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
            conversation.queued_prompts = ["first", "second", "third"]
            await pilot.pause()

            conversation._on_queue_choice("remove:1")
            await pilot.pause()
            assert conversation.queued_prompts == ["first", "third"]
            assert agent.cleared == 1
            assert [text for text, _ in agent.sent] == ["first", "third"]

            agent.sent.clear()
            conversation._on_queue_choice("edit:0")
            await pilot.pause()
            assert conversation.prompt.text == "first"
            assert conversation.queued_prompts == ["third"]
            assert agent.cleared == 2
            assert [text for text, _ in agent.sent] == ["third"]
    print("queue manage: remove/edit re-queue survivors and never cancel the turn")


if __name__ == "__main__":
    asyncio.run(main())