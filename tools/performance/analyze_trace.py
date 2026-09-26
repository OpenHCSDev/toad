"""Bounded trace/action summaries. Inclusive spans overlap and are not additive."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("prefix", type=Path)
parser.add_argument("--slowest", type=int, default=8)
args = parser.parse_args()
trace = json.loads(Path(str(args.prefix) + "-trace.json").read_text())
workload = json.loads(Path(str(args.prefix) + "-actions.json").read_text())
actions = workload["actions"]

def overlaps(event, action):
    return event["ns"] >= action["start_ns"] and event.get("begin_ns", event["ns"]) <= action["end_ns"]

def stats(values):
    values = sorted(values)
    return {"count": len(values), "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[int(.95*(len(values)-1))], 2),
            "p99_ms": round(values[int(.99*(len(values)-1))], 2),
            "max_ms": round(max(values), 2)} if values else {}

selected = [event for event in trace if any(overlaps(event, action) for action in actions)]
groups = defaultdict(list)
for action in actions:
    groups[action["action"].split(":")[0]].extend(event["duration_ms"] for event in trace
        if event["event"] == "loop_gap" and overlaps(event, action))
print(json.dumps({"completed": workload["completed"], "actions": len(actions),
    "overall": {kind: stats([event["duration_ms"] for event in selected if event["event"] == kind])
                for kind in ("loop_gap", "gc", "_refresh_layout", "_compositor_refresh")},
    "by_action": {kind: stats(values) for kind, values in groups.items()}}, indent=2))
for gap in sorted((event for event in selected if event["event"] == "loop_gap"), key=lambda event:-event["duration_ms"])[:args.slowest]:
    spans = [event for event in trace if event["event"] in {"gc", "_refresh_layout", "_compositor_refresh"}
             and event["ns"] >= gap["begin_ns"] and event["begin_ns"] <= gap["ns"]]
    print(json.dumps({"gap_ms": gap["duration_ms"], "actions": [action["action"] for action in actions if overlaps(gap, action)],
                      "overlapping_spans": spans}))
