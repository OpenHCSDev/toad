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
        comms.threads.register(Thread("source", frozenset(), str(root), session_file=str(source)))
        page = comms.transcripts.thread_transcript_page("source")
        history = TranscriptHistory(page, committed=False)
        assert isinstance(history.state, DetachedTranscript)
        assert not history.state.accepts_publication
        app = ToadApp(project_dir=str(root))
        async with app.run_test() as pilot:
            await app.screen.conversation.post(history)
            await pilot.pause()
            assert isinstance(history.state, ProvisionalTranscript)
            assert not history.state.accepts_publication
            history.publish_committed()
            assert isinstance(history.state, LiveTranscript)
            assert history.state.accepts_publication
            assert history.state.reports_coverage
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
    print("transcript lifecycle: real source, provisional mount, commit, synchronous prune admission and removal pass")


if __name__ == "__main__":
    asyncio.run(main())
