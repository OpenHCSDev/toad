"""Compare recorded sidebar spans without combining overlapping durations."""

import json
from pathlib import Path
import statistics
import sys


def stats(values):
    values = sorted(values)
    return {"count": len(values), "median": round(statistics.median(values), 2),
            "p95": round(values[int(.95*(len(values)-1))], 2), "max": round(max(values), 2)} if values else {}


for name in sys.argv[1:]:
    base = Path(name).expanduser()
    workload = json.loads(Path(str(base) + "-actions.json").read_text())
    actions = workload["actions"]
    trace = json.loads(Path(str(base) + "-trace.json").read_text())
    selected = [event for event in trace if any(event["ns"] >= action["start_ns"]
                and event.get("begin_ns", event["ns"]) <= action["end_ns"] for action in actions)]
    events_by_kind = {kind: [event for event in selected if event["event"] == kind]
                      for kind in ("loop_gap", "gc", "sidebar_toggle", "arrange_root", "_refresh_layout", "_compositor_refresh")}
    report = {kind: {**stats([event["duration_ms"] for event in events]),
                     "sum": round(sum(event["duration_ms"] for event in events), 2)}
              for kind, events in events_by_kind.items()}
    report["full_map_arrangements"] = sum(any(frame[1] == "full_map" for frame in event["callers"])
                                           for event in events_by_kind["arrange_root"])
    print(json.dumps({"capture": name, "completed": workload["completed"], "actions": len(actions), **report}, indent=2))
