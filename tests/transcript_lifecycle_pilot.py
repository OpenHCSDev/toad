"""Installed transcript state tracks actual mounting and synchronous prune admission."""

import asyncio
import ast
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import wire
from agent_comms.threads import Thread
from toad.app import ToadApp
from toad.transcript_state import DetachedTranscript, LiveTranscript, ProvisionalTranscript
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    artifacts = Path(__file__).resolve().parents[1] / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="transcript-lifecycle-", dir=artifacts) as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        source = root / "session.jsonl"
        source.write_text(json.dumps({"type": "message", "message": {
            "role": "assistant", "content": "Retain the source"}}) + "\n")
        comms = wire(root / "wire")
        comms.registry.declare(Thread("source", frozenset(), str(root), session_file=str(source)))
        page = comms.transcripts.thread_transcript_page("source")
        history = TranscriptHistory(page, committed=False)
        assert isinstance(history.state, DetachedTranscript)
        assert not history.state.accepts_publication
        app = ToadApp(project_dir=str(root))
        async with app.run_test() as pilot:
            await app.selected_session.conversation.post(history)
            await pilot.pause()
            assert isinstance(history.state, ProvisionalTranscript)
            assert not history.state.accepts_publication
            history.publish_committed()
            assert isinstance(history.state, LiveTranscript)
            assert history.state.accepts_publication
            assert history.state.reports_coverage
            assert history.checkpoint_available
            entered = asyncio.Event()
            release = asyncio.Event()

            async def pending_source_read():
                entered.set()
                await release.wait()
                return page

            operation = history.reserve_source_work()
            operation.schedule(history, pending_source_read)
            await entered.wait()
            assert history.state.accepts_publication
            assert history.state.reports_coverage
            assert not history.state.accepts_source_work
            assert not history.checkpoint_available
            history.request_latest()
            # A parked tab cancels its admitted operation and pending End.
            # Resume admits work on the original source, never a dead worker.
            await history.retire_source(parked=True)
            assert not history.state.accepts_publication
            history.resume_source()
            await pilot.pause()
            assert history.state.accepts_source_work
            assert history.checkpoint_available
            # The actual framework worker is cancelled during source retirement.
            # Its completion cannot restore the prior live source incarnation.
            await history.retire_source()
            await pilot.pause()
            assert not history.state.accepts_publication
            assert not history.state.reports_coverage
            assert not history.state.accepts_source_work
            # remove() marks the real framework node before its Prune message
            # is processed. Publication must be denied during that interval.
            removal = history.remove()
            assert not history.state.accepts_publication
            await removal
            await pilot.pause()
            assert not history.is_attached
            assert not history.state.accepts_publication
        assert source.read_text().find("Retain the source") >= 0
    path = Path(__file__).resolve().parents[1] / "src/toad/widgets/transcript_history.py"
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"_committed", "_closing", "_pruning"}
    print("transcript lifecycle: real source, provisional mount, commit, admitted worker retirement, prune and removal pass")


if __name__ == "__main__":
    asyncio.run(main())
