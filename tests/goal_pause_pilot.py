"""Goal state governs auto-continuation only; changing it never cancels a turn."""

import asyncio
import os
import tempfile
from pathlib import Path

from textual.content import Content

from toad.app import ToadApp


class FakeAgent:
    def __init__(self):
        self.cancel_calls = 0
        self.actions: list[tuple[str, str]] = []

    async def update_goal(self, action, text=""):
        self.actions.append((action, text))
        return None

    async def cancel(self):
        self.cancel_calls += 1

    def get_info(self):
        return Content("Fake agent")

    async def stop(self):
        pass


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-goal-pause-") as directory:
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
            conversation.turn = "agent"  # A turn is in progress.
            for action in ("paused", "active", "blocked", "completed", "clear"):
                await conversation.change_goal(action)
            assert agent.cancel_calls == 0, "changing a goal must not cancel the running turn"
            assert [action for action, _ in agent.actions] == [
                "paused", "active", "blocked", "completed", "clear"
            ]
    print("goal pause: state changes apply without cancelling the running turn")


if __name__ == "__main__":
    asyncio.run(main())