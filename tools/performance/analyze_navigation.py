"""Navigation stage durations and target-mode flushes (not pixel readiness)."""

import json
from pathlib import Path
import sys

base = Path(sys.argv[1]).expanduser()
workload = json.loads(Path(str(base) + "-actions.json").read_text())
trace = json.loads(Path(str(base) + "-trace.json").read_text())
for action in workload["actions"]:
    kind, _, target = action["action"].partition(":")
    if kind not in {"open", "switch-sidebar", "switch"}:
        continue
    label = f"opened:{target}" if kind == "open" else f"switched:{target}"
    snapshot = next(snapshot for snapshot in workload["snapshots"] if snapshot["label"] == label
                    and snapshot["ns"] >= action["start_ns"])
    mode = snapshot["mode"]
    flushes = [event for event in trace if event["event"] == "frame_flushed" and event.get("mode") == mode
               and action["start_ns"] <= event["ns"] <= action["end_ns"]]
    stages = [event for event in trace if event["event"] == "navigation_stage"
              and event["ns"] >= action["start_ns"] and event["begin_ns"] <= action["end_ns"]]
    print(json.dumps({"action": action["action"], "mode": mode,
                      "first_target_flush_ms": round((flushes[0]["ns"]-action["start_ns"])/1e6, 2) if flushes else None,
                      "stages": [{"stage": event["stage"], "duration_ms": round(event["duration_ms"], 2),
                                  "start_ms": round((event["begin_ns"]-action["start_ns"])/1e6, 2)} for event in stages]}))
