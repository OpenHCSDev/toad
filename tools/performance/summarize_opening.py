"""Action-to-target flush and replay/ready completion, excluding no-op tabs."""

import json
from pathlib import Path
import statistics
import sys


def stats(values):
    return {"count": len(values), "min_ms": round(min(values), 2),
            "median_ms": round(statistics.median(values), 2), "max_ms": round(max(values), 2)} if values else {}


for name in sys.argv[1:]:
    base = Path(name).expanduser()
    workload = json.loads(Path(str(base) + "-actions.json").read_text())
    trace = json.loads(Path(str(base) + "-trace.json").read_text())
    report = []
    for action in workload["actions"]:
        kind, _, target = action["action"].partition(":")
        if kind not in {"open", "switch-sidebar", "switch"}:
            continue
        label = f"opened:{target}" if kind == "open" else f"switched:{target}"
        snapshot = next(snapshot for snapshot in workload["snapshots"] if snapshot["label"] == label
                        and snapshot["ns"] >= action["start_ns"])
        mode = snapshot["mode"]
        prior = [snapshot for snapshot in workload["snapshots"] if snapshot["ns"] < action["start_ns"]]
        if kind != "open" and prior and prior[-1]["mode"] == mode:
            continue
        selected = [event for event in trace if action["start_ns"] <= event["ns"] <= snapshot["ns"]]
        flushes = [event for event in selected if event["event"] == "frame_flushed" and event.get("mode") == mode]
        ready = [event for event in selected if event["event"] == "navigation_stage"
                 and event["stage"] == "on_agent_ready" and event.get("mode") == mode]
        report.append({"action": action["action"], "kind": kind,
                       "flush_ms": (flushes[0]["ns"]-action["start_ns"])/1e6 if flushes else None,
                       "ready_handler_end_ms": (ready[-1]["ns"]-action["start_ns"])/1e6 if ready else None})
    print(json.dumps({"capture": name, "completed": workload["completed"],
                      "opening_flush": stats([row["flush_ms"] for row in report if row["kind"] == "open" and row["flush_ms"] is not None]),
                      "opening_ready_handler_end": stats([row["ready_handler_end_ms"] for row in report if row["kind"] == "open" and row["ready_handler_end_ms"] is not None]),
                      "switching_flush": stats([row["flush_ms"] for row in report if row["kind"] != "open" and row["flush_ms"] is not None]),
                      "per_action": [{key: round(value, 2) if isinstance(value, float) else value for key, value in row.items()}
                                     for row in report]}, indent=2))
