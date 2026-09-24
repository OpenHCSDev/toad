"""Sending feedback paints before transport completion and disappears on receipt."""

import asyncio
import os
import tempfile
from pathlib import Path

from toad.acp.messages import InputStarted, PromptQueueUpdate, Update
from runtime_fixture import ToadApp
from toad.widgets.conversation import Conversation
from toad.widgets.prompt import QueueSummary, SendNow
from toad.widgets.user_input import UserInput


class GatedAgent:
    uses_turn_events = True
    server_titles = True

    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sent = []

    async def send_prompt(self, text, **kwargs):
        self.sent.append(text)
        self.started.set()
        await self.release.wait()

    async def stop(self):
        pass


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-send-status-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            agent = GatedAgent()
            conversation.set_reactive(Conversation.agent, agent)
            conversation.agent_ready = True
            conversation.queue_supported = True
            conversation.turn = "agent"
            for key in ("ctrl+enter", "ctrl+y"):
                agent.started.clear()
                agent.release.clear()
                conversation.prompt.text = "urgent follow-up"
                conversation.prompt.focus()
                await pilot.press(key)
                await asyncio.wait_for(agent.started.wait(), 3)
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "Sending next: urgent follow-up" in frame
                agent.release.set()
                conversation.post_message(InputStarted(None))
                conversation.post_message(Update("text", "Already processing the follow-up"))
                await pilot.pause()
                assert not conversation.delivering_prompt
                assert "Sending next" not in conversation.query_one(QueueSummary).render().plain
            # Deferred echo acknowledges delivery; it must not start a sending
            # indicator that then remains for the entire response.
            conversation.post_message(InputStarted("ordinary queued input"))
            await pilot.pause()
            assert not conversation.delivering_prompt
            # Real click/shortcuts with an empty composer target the existing
            # queue head, rather than submitting an empty message. Delivery is
            # already scheduled by the owner; feedback must not resend it.
            for key in (None, "ctrl+enter", "ctrl+y"):
                conversation.post_message(PromptQueueUpdate(["already queued", "still waiting"], []))
                await pilot.pause()
                before = list(agent.sent)
                if key is None:
                    await pilot.click(SendNow)
                else:
                    conversation.prompt.focus()
                    await pilot.press(key)
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "Sending next: already queued" in frame, frame
                assert "Queued (1): still waiting" in frame, frame
                assert agent.sent == before
                # A repeated owner snapshot or repeated click cannot demote the
                # sending status or dispatch a duplicate prompt.
                conversation.post_message(PromptQueueUpdate(["already queued", "still waiting"], []))
                await pilot.click(SendNow)
                await pilot.pause()
                assert "Sending next: already queued" in conversation.query_one(QueueSummary).render().plain
                assert agent.sent == before
                echoed = sum(block.content == "already queued" for block in conversation.query(UserInput))
                conversation.post_message(InputStarted("already queued"))
                await pilot.pause()
                summary = conversation.query_one(QueueSummary).render().plain
                assert "Sending next" not in summary, summary
                assert summary == "Queued (1): still waiting", summary
                assert sum(block.content == "already queued" for block in conversation.query(UserInput)) == echoed + 1
                conversation.post_message(PromptQueueUpdate(["still waiting"], []))
                await pilot.pause()
                assert conversation.query_one(QueueSummary).render().plain == summary
            # Queue cancellation/restoration clears pending presentation too.
            await pilot.click(SendNow)
            await pilot.pause()
            conversation.post_message(PromptQueueUpdate([], ["still waiting"]))
            await pilot.pause()
            assert "Sending next" not in conversation.query_one(QueueSummary).render().plain
            assert conversation.prompt.text == "still waiting"
    print("send status: both shortcuts paint pending status before receipt; no stale sending label")


if __name__ == "__main__":
    asyncio.run(main())
