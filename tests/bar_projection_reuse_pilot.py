"""Only presentation changes should invalidate shared bar preparation."""

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import statistics
import tempfile
import time

from agent_comms.threads import Thread
from agent_comms.comms import wire
from agent_comms.presentation import ThreadView
from agent_comms.goal_waits import GoalWaits

from toad.session_tracker import ExactUnread
from toad.sidebar_preparation import ThreadRowInput, ThreadRowsWork, prepare_thread_presentation
from toad.work_preparation import PreparationRuntime
from work_preparation_pilot import Backend


async def main(observe):
    with tempfile.TemporaryDirectory(prefix="bar-projection-") as directory:
        root = Path(directory)
        comms = wire(root / "wire")
        for index in range(60):
            comms.registry.declare(Thread(f"worker-{index}", frozenset({"shared"}), str(root)))
        # This resource check needs original thread presentations, not wire
        # delivery/unread traversal on a root without native bus admission.
        people = ThreadView.roster(
            comms.registry.snapshot(),
            comms.agents,
            GoalWaits(root / "wire" / GoalWaits.filename),
            show_stopped=True,
            show_archived=False,
        )
        runtime = PreparationRuntime(Backend())
        durations = []
        sources = []
        try:
            for revision in range(16):
                # A polling timestamp changes source identity but none of the
                # label, activity, model, unread, pin or pending-action inputs.
                rows = tuple(ThreadRowInput(replace(person, last_seen=person.last_seen + revision))
                             for person in people)
                before = time.perf_counter()
                result = await runtime.submit(await ThreadRowsWork.capture(runtime, rows))
                durations.append((time.perf_counter() - before) * 1000)
                rendered = [(row.frames[0].plain, row.tooltip.plain, row.busy) for row in result]
                if sources:
                    assert rendered == sources
                else:
                    sources = rendered
            print(json.dumps({"boundary": "worker-result delivery, not frame latency", "rows": len(people),
                              "requests": len(durations), "hits": runtime.hits, "misses": runtime.misses,
                              "retained_bytes": runtime.retained_bytes,
                              "median_ms": round(statistics.median(durations), 2),
                              "max_ms": round(max(durations), 2)}))
            if not observe:
                assert runtime.misses == 1, "Unrendered metadata invalidated every bar's prepared content"
            changed = ThreadRowInput(people[0], unread=ExactUnread(7), pinned=True, action_status="Stopping")
            captured = await ThreadRowsWork.capture(runtime, (ThreadRowInput(people[0]),))
            result = await runtime.submit(ThreadRowsWork(tuple(captured.for_rows({"row": changed}).values())))
            expected = prepare_thread_presentation(changed.presentation())
            assert result[0].frames[0].plain == expected.frames[0].plain
            assert result[0].frames[0].plain.startswith("(7) * ") and result[0].busy
            assert result[0].tooltip.plain == expected.tooltip.plain
        finally:
            await runtime.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", action="store_true")
    asyncio.run(main(parser.parse_args().observe))
