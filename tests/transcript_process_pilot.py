"""Real process/heartbeat evidence and deterministic stale transcript publication races."""

import asyncio
from contextlib import suppress
import multiprocessing
import os
from pathlib import Path
import pickle
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from agent_comms.declarations import Message, MessageRoute, MessageType, TurnRouting
from agent_comms.tool_results import ToolDiff
from textual.app import App

from toad.render_processes import RenderProcessPool
from toad.acp.messages import TranscriptSnapshot
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_fragments import prepare_transcript_fragments, transcript_fragments
from toad.widgets.transcript_history import TranscriptHistory, TranscriptPageView
from runtime_fixture import ToadApp


def observed_parse(function, events):
    """Importable worker probe: timing covers actual fragmentation, not a sleep."""
    started = time.monotonic()
    fragments = function(events)
    return os.getpid(), started, time.monotonic(), fragments


class ObservedPool(RenderProcessPool):
    def __init__(self):
        super().__init__()
        self.observations = []
        self.app = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    def hold(self):
        self.entered.clear()
        self.release.clear()

    async def run(self, function, *args):
        assert function is transcript_fragments
        assert len(args) == 1 and all(isinstance(event, TranscriptEvent) for event in args[0])
        if self.app is not None:
            window = self.app.screen.conversation.window
            assert not self.app._batch_count
            assert window.history_anchor is None and not window.history_lock.locked()
        pid, started, finished, result = await super().run(observed_parse, function, *args)
        self.observations.append((pid, started, finished))
        self.entered.set()
        await self.release.wait()
        return result


def page(text, *, older=False):
    cursor = TranscriptCursor("process-fixture", 1)
    return TranscriptPage((TranscriptEvent("assistant", text),), cursor, cursor, older, False)


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(.005)


async def main():
    pool = ObservedPool()
    beats = []

    async def heartbeat():
        while True:
            beats.append(time.monotonic())
            await asyncio.sleep(.005)

    text = "\n\n".join(
        f"## Heading {i}\n\nParagraph with **bold**, [link](https://example.org), and `code`. " * 3
        for i in range(1800)
    )
    table = "| A | B |\n| --- | --- |\n" + "| cell | value |\n" * 100
    routing = TurnRouting(
        (Message("sender", "#channel", "incoming", MessageType.INFO, timestamp=1),),
        MessageRoute("worker", ("#channel", "peer")),
    )
    events = (
        TranscriptEvent("user", "Incoming message", routing=routing),
        TranscriptEvent("assistant", text, routing=routing),
        TranscriptEvent("thinking", "A thought\n\n" + table),
        TranscriptEvent("notice", "Notice"), TranscriptEvent("sent", "Sent"),
        TranscriptEvent("tool_start", tool_call_id="edit/1", tool_name="edit",
                        raw_input={"path": "file.py", "edits": [{"old": "a", "new": "b"}]}),
        TranscriptEvent("tool_end", "edited", tool_call_id="edit/1", tool_name="edit",
                        diff=ToolDiff("--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-a\n+b\n")),
        TranscriptEvent("assistant", "```text\n" + "fenced line\n" * 100 + "```\n\n" +
                        "\n".join(f"- item {i}" for i in range(100))),
    )
    assert pickle.loads(pickle.dumps(events)) == events
    expected = transcript_fragments(events)
    task = asyncio.create_task(heartbeat())
    try:
        actual = await prepare_transcript_fragments(events, pool)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert actual == expected == pickle.loads(pickle.dumps(actual))
    pid, started, finished = pool.observations[-1]
    during = [beat for beat in beats if started <= beat <= finished]
    assert pid != os.getpid() and len(during) >= 3, (pid, during, finished - started)
    gaps = [b - a for a, b in zip([started, *during], [*during, finished])]
    assert max(gaps) < .2, max(gaps)

    # A standalone Textual app has neither Toad services nor an app pool. The
    # helper's request-owned fallback must close its children before returning.
    baseline_children = {child.pid for child in multiprocessing.active_children()}
    async with App().run_test():
        fallback = await prepare_transcript_fragments((TranscriptEvent("assistant", table * 8),))
    assert fallback == transcript_fragments((TranscriptEvent("assistant", table * 8),))
    assert {child.pid for child in multiprocessing.active_children()} == baseline_children

    with tempfile.TemporaryDirectory(prefix="toad-transcript-process-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        pool.app = app
        # Keep edge requests deterministic here; real scrolling is exercised by
        # transcript_history/history_scroll_frames/long_message pilots.
        with patch.object(ToadApp, "render_processes", property(lambda self: pool), create=True), \
                patch.object(TranscriptHistory, "_check_edges", lambda self: None):
            async with app.run_test(size=(90, 35)) as pilot:
                await pilot.pause()
                conversation = app.screen.conversation
                live_text = text[:30000]
                snapshot = page(live_text)

                async def load(**kwargs):
                    return snapshot

                agent = SimpleNamespace(get_transcript_page=load)
                with patch.object(type(conversation), "agent", property(lambda self: agent)):
                    before = tuple(conversation.contents.children)
                    pool.hold()
                    stale_snapshot = asyncio.create_task(conversation.on_transcript_snapshot(
                        TranscriptSnapshot(snapshot.events, snapshot),
                    ))
                    await until(pool.entered.is_set)
                    conversation._transcript_generation += 1
                    pool.release.set()
                    await stale_snapshot
                    assert tuple(conversation.contents.children) == before
                    with patch("toad.widgets.transcript_history.transcript_fragments", side_effect=AssertionError):
                        await conversation.on_transcript_snapshot(TranscriptSnapshot(snapshot.events, snapshot))
                    first = conversation.contents.query_one(TranscriptHistory)
                    assert first.pages[0].fragments == transcript_fragments(snapshot.events)
                await conversation.contents.remove_children()
                response = await conversation.post(AgentResponse("initial"))
                await pilot.pause()

                pool.hold()
                obsolete = asyncio.create_task(response._update_content(live_text, append=False))
                await until(pool.entered.is_set)
                latest = asyncio.create_task(response._update_content("latest", append=False))
                await asyncio.sleep(0)
                pool.release.set()
                await asyncio.gather(obsolete, latest)
                assert response.source == "latest" and response._paged is None

                pool.hold()
                cancelled = asyncio.create_task(response._update_content(live_text, append=False))
                await until(pool.entered.is_set)
                cancelled.cancel()
                with suppress(asyncio.CancelledError):
                    await cancelled
                pool.release.set()
                await response.append(" preserved")
                assert response.source == "latest preserved" and response._paged is None

                ui_beats = []
                timer = app.set_interval(.005, lambda: ui_beats.append(time.monotonic()))
                await response.update(text)
                timer.stop()
                _, ui_started, ui_finished = pool.observations[-1]
                during_ui_parse = [beat for beat in ui_beats if ui_started <= beat <= ui_finished]
                assert len(during_ui_parse) >= 3
                ui_gaps = [b - a for a, b in zip(
                    [ui_started, *during_ui_parse], [*during_ui_parse, ui_finished],
                )]
                assert max(ui_gaps) < .2, max(ui_gaps)
                history = response._paged
                assert history is not None
                assert history.pages[0].page.events[0].text == text
                # A precomputed page must not silently parse again in __init__.
                with patch("toad.widgets.transcript_history.transcript_fragments", side_effect=AssertionError):
                    TranscriptPageView(page(text), fragments=history.pages[0].fragments)

                pool.hold()
                stale_live = asyncio.create_task(history.update_live(page(live_text + "\n\nOLD")))
                await until(pool.entered.is_set)
                await history.update_live(page("NEW"))
                pool.release.set()
                await stale_live
                assert history.pages[0].page.events[0].text == "NEW"

                async def load(**kwargs):
                    return page(live_text)

                history.loader = load
                before = tuple(history.pages)
                pool.hold()
                edge = asyncio.create_task(history._load_page(True))
                await until(pool.entered.is_set)
                conversation.window.release_anchor()
                pool.release.set()
                await edge
                assert tuple(history.pages) == before

                pool.hold()
                jump = asyncio.create_task(history._jump_latest())
                await until(pool.entered.is_set)
                conversation.window.release_anchor()
                pool.release.set()
                await jump
                assert tuple(history.pages) == before and not conversation.window.follows_tail

                pool.hold()
                detached = asyncio.create_task(response._update_content(live_text + "\n\nDETACHED", append=False))
                await until(pool.entered.is_set)
                closing = asyncio.ensure_future(response.remove())
                await until(lambda: not response.is_attached or response._closing)
                pool.release.set()
                await asyncio.gather(detached, closing)
                assert "DETACHED" not in response.source
                assert app._exception is None
        pool.app = None
    await pool.aclose()
    print({"foreground_pid": os.getpid(), "parse_pid": pid, "parse_seconds": finished - started,
           "foreground_heartbeats_during_parse": len(during), "max_parse_loop_gap_ms": max(gaps) * 1000,
           "textual_timer_heartbeats_during_parse": len(during_ui_parse),
           "max_textual_timer_gap_ms": max(ui_gaps) * 1000,
           "exact_fragments": len(actual), "stale_cancelled_detached_and_scroll_intent": "passed"})


if __name__ == "__main__":
    asyncio.run(main())
