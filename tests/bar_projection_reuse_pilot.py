"""Only presentation changes should invalidate shared bar preparation."""

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import statistics
import tempfile
import time

from agent_comms import Thread, wire

from toad.sidebar_preparation import ThreadRowInput, ThreadRowsWork, prepare_thread_row
from toad.work_preparation import PreparationRuntime
from work_preparation_pilot import Backend


async def main(observe):
    with tempfile.TemporaryDirectory(prefix="bar-projection-") as directory:
        root = Path(directory)
        comms = wire(root / "wire")
        for index in range(60):
            comms.register(Thread(f"worker-{index}", frozenset({"shared"}), str(root)))
        people = comms.viewer_snapshot(str(root), show_stopped=True).threads
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
                result = await runtime.submit(ThreadRowsWork(rows))
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
            changed = ThreadRowInput(people[0], unread=7, pinned=True, action_status="Stopping")
            result = await runtime.submit(ThreadRowsWork((changed,)))
            expected = prepare_thread_row(changed)
            assert result[0].frames[0].plain == expected.frames[0].plain
            assert result[0].frames[0].plain.startswith("(7) * ") and result[0].busy
            assert result[0].tooltip.plain == expected.tooltip.plain
        finally:
            await runtime.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", action="store_true")
    asyncio.run(main(parser.parse_args().observe))
