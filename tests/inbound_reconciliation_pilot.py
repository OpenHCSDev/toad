"""Mounted inbound continuity across bounded saved pages and concurrent live arrivals."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import (
    Message,
    MessageType,
    Thread,
    TranscriptCursor,
    TranscriptEvent,
    TranscriptPage,
    TurnRouting,
    wire,
)
from committed_history_pilot import SnapshotAgent
from runtime_fixture import ToadApp

from toad.acp.messages import IncomingMessage as IncomingEvent
from toad.widgets import transcript_fragments
from toad.widgets.agent_response import AgentResponse
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.message_filter import ALL_CATEGORIES, MessageCategory
from toad.widgets.transcript_history import TranscriptHistory


class TestAgent(SnapshotAgent):
    def __init__(self, page):
        super().__init__(page)
        self.ready = True
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def get_transcript_page(self, **kwargs):
        self.entered.set()
        await self.release.wait()
        return self.page

    async def get_goal_snapshot(self):
        return None, None

    async def get_input_delivery(self, **kwargs):
        return {
            "inputs": [],
            "historicalCount": 0,
            "dismissedHistoricalCount": 0,
            "historicalInputs": [],
        }


def routed(sequence, text):
    message = Message("peer", "owner", text, MessageType.INFO, seq=sequence)
    return TranscriptEvent("user", text, routing=TurnRouting((message,), None))


def inbound(view):
    return [block.text for block in view.query(IncomingMessage)]


async def checkpoint(view):
    view.window.anchor()
    view._transcript_dirty = view._needs_transcript_checkpoint = True
    await view._compact_committed_history().wait()


async def arrivals(view, pilot):
    """No saved identity: retain notices, even across fetch and preparation awaits."""
    cursor = TranscriptCursor("", 0)
    agent = TestAgent(
        TranscriptPage(
            (TranscriptEvent("assistant", "saved reply"),), cursor, cursor, False, False
        )
    )
    view.set_reactive(type(view).agent, agent)
    view.agent_ready = True
    await view.on_incoming_message(IncomingEvent("peer", "owner", "before read", 41))
    agent.release.clear()
    prepare_entered, prepare_release = asyncio.Event(), asyncio.Event()
    original = transcript_fragments.prepare_transcript_fragments

    async def prepare(*args, **kwargs):
        prepare_entered.set()
        await prepare_release.wait()
        return await original(*args, **kwargs)

    with patch.object(transcript_fragments, "prepare_transcript_fragments", prepare):
        work = asyncio.create_task(checkpoint(view))
        await asyncio.wait_for(agent.entered.wait(), 5)
        await view.on_incoming_message(
            IncomingEvent("peer", "owner", "during read", 42)
        )
        await view.post(AgentResponse("ordinary during read"))
        agent.release.set()
        await asyncio.wait_for(prepare_entered.wait(), 5)
        await view.on_incoming_message(
            IncomingEvent("peer", "owner", "during preparation", 43)
        )
        await view.post(AgentResponse("ordinary during preparation"))
        prepare_release.set()
        await work
    await pilot.pause()
    assert inbound(view) == [
        "before read",
        "during read",
        "during preparation",
    ], inbound(view)
    sources = [block.source for block in view.query(AgentResponse)]
    assert (
        "ordinary during read" in sources and "ordinary during preparation" in sources
    )
    # An older saved page later proves the exact identity. The saved counterpart
    # owns that row; the live one must disappear without removing other notices.
    history = view.query_one(TranscriptHistory)
    saved = TranscriptPage((routed(41, "before read"),), cursor, cursor, False, False)
    await history._extend_and_trim(
        history.pages[0],
        True,
        False,
        saved,
        type("Position", (), {"follow_tail": True})(),
        set(),
        transcript_fragments.transcript_fragments(saved.events),
    )
    await pilot.pause()
    assert inbound(view).count("before read") == 1, inbound(view)
    assert "during read" in inbound(view) and "during preparation" in inbound(view)
    assert not any(
        isinstance(child, IncomingMessage) and child.text == "before read"
        for child in view.contents.children
    )
    stale = history.Covered((routed(42, "during read"),), history)
    await history.remove()
    await view.on_transcript_history_covered(stale)
    assert "during read" in inbound(
        view
    ), "detached page cannot retire a current live row"


async def disk_history(view, pilot, root):
    """A real saved range and filtered older overlay survive a newer bounded tail."""
    comms = wire(root / "wire")
    comms.register(Thread("owner", frozenset(), str(root)))
    session = root / "session.jsonl"
    session.touch()
    comms.attach_session("owner", str(session))

    def append(entry, role, text, sequence=None):
        row = {
            "type": "message",
            "id": entry,
            "message": {"role": role, "content": [{"type": "text", "text": text}]},
        }
        if role == "toolResult":
            row["message"].update(toolCallId=entry, toolName="read", isError=False)
        with session.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        if sequence is not None:
            comms.transcript_routes.record(
                str(session), (entry,), routed(sequence, text).routing
            )

    append("old-inbound", "user", "OLDER_INBOUND", 51)
    append("old-tool", "toolResult", "x" * 70_000)
    append("initial-tail", "assistant", "initial saved reply")

    class DiskAgent(TestAgent):
        async def get_transcript_page(self, **kwargs):
            return comms.thread_transcript_page("owner", **kwargs)

    agent = DiskAgent(None)
    view.set_reactive(type(view).agent, agent)
    view.agent_ready = True
    view.visible_categories = ALL_CATEGORIES - {
        MessageCategory.TOOL,
        MessageCategory.THINKING,
    }
    history = TranscriptHistory(
        await agent.get_transcript_page(), agent.get_transcript_page
    )
    await view.contents.mount(history)
    async with asyncio.timeout(8):
        while "OLDER_INBOUND" not in inbound(view):
            await pilot.pause(0.05)
    overlay = history._filter_overlay
    assert overlay is not None
    append("new-inbound", "user", "NEWER_INBOUND", 52)
    append("new-tool", "toolResult", "y" * 70_000)
    append("already-saved", "user", "SAVED_BEFORE_NOTICE", 53)
    append("new-tail", "assistant", "new saved reply")
    assert not any(
        e.routing and e.routing.requests[0].seq in {51, 52}
        for e in (await agent.get_transcript_page()).events
    )
    await view.on_incoming_message(IncomingEvent("peer", "owner", "NEWER_INBOUND", 52))
    await checkpoint(view)
    await pilot.pause()
    assert history.is_attached and history._filter_overlay is overlay
    assert inbound(view).count("OLDER_INBOUND") == 1, inbound(view)
    assert inbound(view).count("NEWER_INBOUND") == 1, inbound(view)
    await view.on_incoming_message(
        IncomingEvent("peer", "owner", "SAVED_BEFORE_NOTICE", 53)
    )
    await pilot.pause()
    assert inbound(view).count("SAVED_BEFORE_NOTICE") == 1, inbound(view)
    await checkpoint(view)
    await pilot.pause()
    assert history.is_attached and inbound(view).count("OLDER_INBOUND") == 1
    assert inbound(view).count("NEWER_INBOUND") == 1
    # One oversized prose row still advances through small fragment batches.
    # All its fragments remain reachable by the existing backward pager.
    long_text = "\n\n".join(f"Long paragraph {i} " + "z" * 300 for i in range(220))
    append("long-prose", "assistant", long_text)
    peak = 0
    original = history._extend_and_trim

    async def measured(*args, **kwargs):
        nonlocal peak
        await original(*args, **kwargs)
        peak = max(peak, history.widget_count)

    with patch.object(history, "_extend_and_trim", measured):
        await checkpoint(view)
    assert peak <= history.widget_limit + 100, (peak, history.widget_limit)
    assert history.pages[-1].stop == len(history.pages[-1].fragments)
    assert history.has_older
    assert history.pages[-1].page.after.offset == session.stat().st_size
    tail = history.pages[-1]
    original_start = tail.start
    assert original_start > 0, "large saved row should keep only a bounded mounted tail"
    await pilot.pause()
    assert (
        history._filter_before is None
    ), "eviction must not leave a cursor across omitted fragments"
    view.visible_categories = ALL_CATEGORIES
    history._loading = True
    view.window.release_anchor()
    view.window.scroll_to(y=1, animate=False, immediate=True)
    await pilot.pause()
    history._loading = False
    await history._load_page(True)
    await pilot.pause()
    assert tail.start < original_start, "omitted fragments must remain pageable"


async def main():
    for case in (arrivals, disk_history):
        with tempfile.TemporaryDirectory(prefix="toad-inbound-reconcile-") as directory:
            root = Path(directory)
            os.environ.update(
                XDG_CONFIG_HOME=str(root / "config"),
                XDG_STATE_HOME=str(root / "state"),
                XDG_DATA_HOME=str(root / "data"),
                AGENT_COMMS_ROOT=str(root / "wire"),
            )
            app = ToadApp(project_dir=str(root))
            async with app.run_test(size=(110, 40)) as pilot:
                await pilot.pause()
                view = app.screen.conversation
                async with asyncio.timeout(30):
                    if case is disk_history:
                        await case(view, pilot, root)
                    else:
                        await case(view, pilot)
                assert app._exception is None
    print(
        "inbound reconciliation: live races, exact saved coverage, filtered continuity, bounded oversized row passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
