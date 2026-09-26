"""Attribute cold-open layout passes to their recorded callers."""

from collections import Counter
import json
from pathlib import Path
import sys

base = Path(sys.argv[1]).expanduser()
workload = json.loads(Path(str(base) + "-actions.json").read_text())
trace = json.loads(Path(str(base) + "-trace.json").read_text())
for action in [a for a in workload["actions"] if a["action"].startswith("open:")][:2]:
    events = [event for event in trace if event["ns"] >= action["start_ns"]
              and event.get("begin_ns", event["ns"]) <= action["end_ns"]]
    counts, durations = Counter(), Counter()
    for event in events:
        if event["event"] == "arrange_root":
            key = tuple(tuple(frame) for frame in event["callers"])
            counts[key] += 1
            durations[key] += event["duration_ms"]
    print(json.dumps({"action": action["action"], "layout_triggers": [
        {"stack": key, "count": counts[key], "total_ms": round(duration, 2)}
        for key, duration in durations.most_common()]}, indent=2))
