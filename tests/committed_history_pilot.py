"""Committed model history bounds the complete live view, not only individual messages."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from textual.content import Content
from thread_activation_pilot import FrameApp
from toad.acp.agent import Agent
from toad.acp.messages import TranscriptChanged, TurnSettled
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory


class SnapshotAgent(Agent):
    def __init__(self, page):
        self.page = page
        self.ready = False

    def get_info(self):
        return Content("Snapshot")

    @property
    def transcript_ready(self):
        return self.ready

    async def get_goal(self):
        return None

    async def get_goal_snapshot(self):
        return None, None

    async def get_input_delivery(self, **kwargs):
        return {"inputs": [], "historicalCount": 0, "dismissedHistoricalCount": 0,
                "historicalInputs": []}

    async def get_transcript_page(self, **kwargs):
        assert self.ready, "Compaction must wait for session metadata"
        return self.page

    async def stop(self):
        pass


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-committed-window-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            await conversation.contents.mount(*[AgentResponse(f"Old block {i}\n\nAnother paragraph") for i in range(100)])
            await pilot.pause()
            assert len(list(conversation.contents.query("*"))) > 250
            cursor = TranscriptCursor("", 0)
            page = TranscriptPage(
                tuple(TranscriptEvent("assistant", f"Saved paragraph {i}") for i in range(40))
                + (TranscriptEvent("assistant", "Canonical final reply"),),
                cursor, cursor, False, False,
            )
            agent = SnapshotAgent(page)
            conversation.set_reactive(type(conversation).agent, agent)
            conversation.prompt.text = "Keep my draft"
            conversation.window.anchor()
            conversation.post_message(TranscriptChanged())
            await pilot.pause()
            assert not conversation.contents.query(TranscriptHistory)
            agent.ready = True
            # Cancellation settles the active turn, then replaces accumulated
            # live widgets with the committed transcript. That replacement must
            # preserve follow intent on every painted frame, not reanchor later.
            conversation._managed_turn_id = "cancelled-turn"
            conversation.busy_count = 1
            conversation.turn = "agent"
            app.frames = []
            conversation.post_message(TurnSettled("cancelled-turn", agent=agent, sequence=1))
            conversation.post_message(TranscriptChanged())
            async with asyncio.timeout(5):
                while not conversation.contents.query(TranscriptHistory):
                    await asyncio.sleep(.02)
            await pilot.pause()
            painted = [frame for frame in app.frames if "Saved paragraph" in frame[3]
                       or "Canonical final reply" in frame[3]]
            assert painted and all(y == maximum and "Canonical final reply" in text
                                   for _, y, maximum, text in painted), painted
            assert conversation.turn == "client" and conversation.busy_count == 0
            assert conversation.window.follows_tail
            assert len(list(conversation.contents.query("*"))) < 100
            assert conversation.prompt.text == "Keep my draft"
    print("committed history: bounded model projection replaces accumulated live trees")


if __name__ == "__main__":
    asyncio.run(main())
