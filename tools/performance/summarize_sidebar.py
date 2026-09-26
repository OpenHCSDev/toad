"""Per-action sidebar timing and unexpected full-map layout callers."""

import json
from pathlib import Path
import statistics
import sys


for name in sys.argv[1:]:
    base = Path(name).expanduser()
    actions = json.loads(Path(str(base) + "-actions.json").read_text())
    trace = json.loads(Path(str(base) + "-trace.json").read_text())
    print(name, "completed:", actions["completed"])
    for action in actions["actions"]:
        events = [event for event in trace if event["ns"] >= action["start_ns"]
                  and event.get("begin_ns", event["ns"]) <= action["end_ns"]]
        report = {"action": action["action"]}
        for kind in ("sidebar_toggle", "loop_gap", "gc", "_refresh_layout", "_compositor_refresh", "arrange_root"):
            matched = [event for event in events if event["event"] == kind]
            durations = [event["duration_ms"] for event in matched]
            report[kind] = {"count": len(durations), "max": round(max(durations, default=0), 2),
                            "sum": round(sum(durations), 2)}
        report["arrange_callers"] = [event["callers"] for event in events if event["event"] == "arrange_root"
                                     and any(frame[1] == "full_map" for frame in event["callers"])]
        print(json.dumps(report))
    gaps = [event["duration_ms"] for event in trace if event["event"] == "loop_gap"
            and any(event["ns"] >= action["start_ns"] and event["begin_ns"] <= action["end_ns"]
                    for action in actions["actions"])]
    gaps.sort()
    print("gaps:", {"median": statistics.median(gaps), "p95": gaps[int(.95*(len(gaps)-1))], "max": max(gaps)})
