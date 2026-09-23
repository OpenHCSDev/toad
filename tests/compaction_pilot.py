"""Compaction publishes readable content and does not stall the view's events."""

import asyncio
import os
import tempfile
from pathlib import Path

from toad.acp.messages import Update, TurnStarted, TurnSettled
from runtime_fixture import ToadApp
from toad.messages import UserInputSubmitted
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation, TurnActivity
from time import time


class CompactAgent:
    def __init__(self, conversation):
        self.conversation = conversation
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.started_at = time() - 40
        self.summary = "\n\n".join(f"Decision {i}: " + "Keep the design findings. " * 12 for i in range(35))
        self.summary += "\n\nCOMPACTION-SUMMARY-END"

    async def compact_context(self, instructions=None):
        self.started.set()
        self.conversation.post_message(TurnStarted("compaction", self.started_at, "working", "Compacting context"))
        await self.release.wait()
        self.conversation.post_message(Update("text", "## Context compacted\n\n" + self.summary))
        self.conversation.post_message(TurnSettled("compaction"))
        return {"ok": True, "summary": self.summary}

    async def stop(self):
        pass


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-compaction-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            await conversation.post(AgentResponse("An earlier answer."))
            agent = CompactAgent(conversation)
            conversation.set_reactive(Conversation.agent, agent)
            conversation.post_message(UserInputSubmitted("/compact", False))
            await asyncio.wait_for(agent.started.wait(), 3)
            processed = asyncio.Event()
            conversation.call_later(processed.set)
            try:
                await asyncio.wait_for(processed.wait(), 3)
                await pilot.pause()
                status = conversation.query_one(TurnActivity)
                assert status.started_at == agent.started_at
                assert "Compacting context" in status.render().plain
                assert "elapsed" in status.render().plain
                conversation.post_message(TurnStarted("compaction", agent.started_at, "working", "Compacting context"))
                await pilot.pause()
                assert conversation.busy_count == 1 and status.started_at == agent.started_at
            finally:
                agent.release.set()
            await pilot.pause()
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "COMPACTION-SUMMARY-END" in frame, frame
            assert conversation.busy_count == 0 and not status.display
            assert sum("## Context compacted" in block.source
                       for block in conversation.contents.children if isinstance(block, AgentResponse)) == 1
    print("compaction: summary visible once, event handling remains responsive")


if __name__ == "__main__":
    asyncio.run(main())
