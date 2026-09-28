"""Mounted inbound continuity across bounded saved pages and concurrent live arrivals."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.messages import Message, MessageType
from agent_comms.threads import Thread
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript, UserTranscript
from agent_comms.routing import TurnRouting
from agent_comms.comms import wire
from committed_history_pilot import SnapshotAgent
from runtime_fixture import ToadApp
from textual.selection import SELECT_ALL
from textual.worker import WorkerCancelled

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
    return UserTranscript(text, routing=TurnRouting((message,), None))


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
            (AssistantTranscript('saved reply'),), cursor, cursor, False, False
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


async def provisional_history(view, pilot):
    """Rejected replacement mounts never acquire ownership of live notices."""
    cursor = TranscriptCursor("provisional", 1)
    agent = TestAgent(TranscriptPage(
        (routed(41, "saved notice"), AssistantTranscript('saved reply')),
        cursor, cursor, False, False,
    ))
    view.set_reactive(type(view).agent, agent)
    view.agent_ready = True
    await view.on_incoming_message(IncomingEvent("peer", "owner", "saved notice", 41))
    notice = view.contents.query_one(IncomingMessage)
    live = await view.post(AgentResponse("live reply"))
    original = view.contents.mount
    for cancel in (False, True):
        entered, release = asyncio.Event(), asyncio.Event()

        async def mount(*widgets, **kwargs):
            result = await original(*widgets, **kwargs)
            if any(isinstance(widget, TranscriptHistory) for widget in widgets):
                entered.set()
                await release.wait()
            return result

        with patch.object(view.contents, "mount", mount):
            view.window.anchor()
            view._transcript_dirty = view._needs_transcript_checkpoint = True
            work = view._compact_committed_history()
            await asyncio.wait_for(entered.wait(), 5)
            await pilot.pause()
            assert notice.is_attached, "Provisional page retired a live notice before acceptance"
            if cancel:
                work.cancel()
            else:
                view.window.release_anchor()
            release.set()
            try:
                await work.wait()
            except WorkerCancelled:
                assert cancel
        await pilot.pause()
        assert notice.is_attached and live.is_attached
        assert not view.contents.query(TranscriptHistory), "Rejected replacement leaked its pager"
    await checkpoint(view)
    await pilot.pause()
    assert not notice.is_attached and not live.is_attached
    assert inbound(view).count("saved notice") == 1
    # A selected wire notice can outlive its Covered event. Once released, the
    # same accepted source must still prove coverage without requiring new pages.
    protected = IncomingMessage("peer", "saved notice", "owner", sequence=41)
    await view.contents.mount(protected)
    view.screen.selections = {protected: SELECT_ALL}
    history = view.contents.query_one(TranscriptHistory)
    await view.on_transcript_history_covered(history.Covered(agent.page.events, history))
    assert protected.is_attached
    view.screen.clear_selection()
    await checkpoint(view)
    assert not protected.is_attached


async def disk_history(view, pilot, root):
    """A real saved range and filtered older overlay survive a newer bounded tail."""
    comms = wire(root / "wire")
    comms.threads.register(Thread("owner", frozenset(), str(root)))
    session = root / "session.jsonl"
    session.touch()
    comms.threads.attach_session("owner", str(session))

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
            comms.transcripts.routes.record(
                str(session), (entry,), routed(sequence, text).routing
            )

    append("old-inbound", "user", "OLDER_INBOUND", 51)
    append("old-tool", "toolResult", "x" * 70_000)
    append("initial-tail", "assistant", "initial saved reply")

    class DiskAgent(TestAgent):
        async def get_transcript_page(self, **kwargs):
            return comms.transcripts.thread_transcript_page("owner", **kwargs)

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
    overlay = history.filter.overlay
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
    assert history.is_attached and history.filter.overlay is overlay
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
        history.filter.before is None
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
    for case in (arrivals, provisional_history, disk_history):
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
