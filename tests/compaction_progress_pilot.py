"""ACP byte progress remains distinct from calls remaining and completion."""

import asyncio
import os
from pathlib import Path
import tempfile

from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.acp.messages import CompactionUpdate, TurnStarted
from toad.widgets.conversation import TurnActivity


def packet(phase="progress", **progress):
    return {
        "sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": ""},
        "_meta": {"agentComms": {"compaction": {"phase": phase, **progress}}},
    }


def fixture_agent(root):
    return Agent(root, {"name": "Fixture", "identity": "fixture", "short_name": "fixture",
                       "run_command": {"*": "true"}, "protocol": "acp"}, "fixture")


def check_protocol(root):
    captured = []

    class Target:
        def post_message(self, message):
            captured.append(message)
            return True

    agent = fixture_agent(root)
    agent._message_target = Target()
    agent.rpc_session_update("fixture", packet(
        chunkIndex=0, sourceBytesDone=0, sourceBytesTotal=800, summaryPhase="history"))
    message = captured.pop()
    assert isinstance(message, CompactionUpdate)
    assert (message.chunk_index, message.source_bytes_done, message.source_bytes_total,
            message.summary_phase) == (0, 0, 800, "history")
    agent.rpc_session_update("fixture", packet(
        chunkIndex=3, sourceBytesDone=800, sourceBytesTotal=800, summaryPhase="shrink"))
    assert captured.pop().summary_phase == "shrink"
    agent.rpc_session_update("fixture", packet(
        chunkIndex=3, sourceBytesDone=800, sourceBytesTotal=800, summaryPhase="synthesis"))
    assert captured.pop().summary_phase == "synthesis"
    # Old senders and malformed counters use the existing summary-step fallback.
    for values in ({}, {"sourceBytesDone": True, "sourceBytesTotal": 800},
                   {"sourceBytesDone": 0, "sourceBytesTotal": 0},
                   {"sourceBytesDone": 801, "sourceBytesTotal": 800},
                   {"sourceBytesDone": -1, "sourceBytesTotal": 800},
                   {"sourceBytesDone": 1, "sourceBytesTotal": "800"}):
        agent.rpc_session_update("fixture", packet(chunkIndex=2, **values))
        message = captured.pop()
        assert message.chunk_index == 2
        assert message.source_bytes_done is None and message.source_bytes_total is None


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-compaction-progress-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        check_protocol(root)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 34)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            agent = fixture_agent(root)
            agent._message_target = view
            view.post_message(TurnStarted("active-turn", None, "working", "Thinking"))
            await pilot.pause()
            status = view.query_one(TurnActivity)

            async def update(phase="progress", **values):
                agent.rpc_session_update("fixture", packet(phase, **values))
                await pilot.pause()
                assert view.busy_count == 1
                return status.render().plain

            assert "Compacting context" in await update("start")
            initial = await update(chunkIndex=0, sourceBytesDone=0,
                                   sourceBytesTotal=800, summaryPhase="history")
            assert "0% of input processed" in initial and "0 summaries" in initial
            progress = await update(chunkIndex=2, sourceBytesDone=400,
                                    sourceBytesTotal=800, summaryPhase="current-turn")
            assert "50% of input processed" in progress and "2 summaries" in progress
            shrinking = await update(chunkIndex=3, sourceBytesDone=800,
                                     sourceBytesTotal=800, summaryPhase="shrink")
            assert "last step: summary shrink" in shrinking and "100% of input processed" in shrinking
            assert "3 summaries" in shrinking and "remaining" not in shrinking
            ended = await update("end", summary="Finished")
            assert "input processed" not in ended and "summary shrink" not in ended
            await update("start")
            fallback = await update(chunkIndex=1)
            assert "step 1 completed" in fallback and "%" not in fallback
            aborted = await update("abort", summary="Stopped")
            assert "step 1" not in aborted and "input processed" not in aborted
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("compaction progress: typed totals, zero-start, input percentage, shrink, legacy fallback, cleanup")


if __name__ == "__main__":
    asyncio.run(main())
