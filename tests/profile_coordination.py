"""Cold scan versus repeated polling on a long, unchanged coordination log."""

import json
import tempfile
import time
from pathlib import Path

from agent_comms import Thread, wire


with tempfile.TemporaryDirectory(prefix="toad-poll-profile-") as directory:
    root = Path(directory)
    comms = wire(root)
    for name in ("sender", "reader"):
        comms.register(Thread(name, frozenset({"team"}), str(root)))
    count = 20000
    (root / "bus.jsonl").write_text("".join(
        json.dumps({"seq": i + 1, "from": "sender", "to": "#team", "type": "info",
                    "text": "A historical coordination update. " * 10, "ts": float(i)}) + "\n"
        for i in range(count)
    ))
    start = time.perf_counter()
    cold = comms.coordination_snapshot("reader")
    cold_seconds = time.perf_counter() - start
    start = time.perf_counter()
    for _ in range(100):
        snapshot = comms.coordination_snapshot("reader")
        assert snapshot == cold
    warm_seconds = (time.perf_counter() - start) / 100
    assert cold.unread["#team"] == count
    print(json.dumps({"messages": count, "cold_scan_ms": cold_seconds * 1000,
                      "unchanged_poll_ms": warm_seconds * 1000,
                      "scan_to_poll_ratio": cold_seconds / warm_seconds}, indent=2))
