"""Summarize cold-open navigation, construction and mount observations."""

from collections import Counter
import json
from pathlib import Path
import sys

base = Path(sys.argv[1]).expanduser()
workload = json.loads(Path(str(base) + "-actions.json").read_text())
trace = json.loads(Path(str(base) + "-trace.json").read_text())
opens = [action for action in workload["actions"] if action["action"].startswith("open:")]
for action in opens[:int(sys.argv[2]) if len(sys.argv) > 2 else len(opens)]:
    events = [event for event in trace if event["ns"] >= action["start_ns"]
              and event.get("begin_ns", event["ns"]) <= action["end_ns"]]
    stages = [event for event in events if event["event"] == "navigation_stage"]
    constructors = [event for event in events if event["event"] == "widget_construct"]
    mounts = [event for event in events if event["event"] == "widget_mount"]
    print(json.dumps({"action": action["action"], "constructors": len(constructors),
                      "constructor_ms": round(sum(event["duration_ms"] for event in constructors), 2),
                      "classes": Counter(event["widget"] for event in constructors).most_common(12),
                      "stages": [{"stage": event["stage"], "owner": event.get("owner"),
                                  "start_ms": round((event["begin_ns"]-action["start_ns"])/1e6, 2),
                                  "duration_ms": round(event["duration_ms"], 2)} for event in stages],
                      "slow_mounts": [{"widget": event["widget"], "ms": round(event["duration_ms"], 2),
                                       "start_ms": round((event["begin_ns"]-action["start_ns"])/1e6, 2)}
                                      for event in sorted(mounts, key=lambda event:-event["duration_ms"])[:12]]}, indent=2))
