"""Inspect explicit layout invalidation causes during recorded actions."""

from collections import Counter
import json
from pathlib import Path
import sys

base = Path(sys.argv[1]).expanduser()
actions = json.loads(Path(str(base) + "-actions.json").read_text())["actions"]
trace = json.loads(Path(str(base) + "-trace.json").read_text())
for action in actions:
    events = [event for event in trace if event["ns"] >= action["start_ns"]
              and event.get("begin_ns", event["ns"]) <= action["end_ns"]]
    requests = [event for event in events if event["event"] == "layout_request"]
    print(action["action"], Counter(event["widget"] for event in requests))
    for event in events:
        if event["event"] in {"layout_request", "_refresh_layout", "sidebar_toggle"}:
            print(json.dumps({**event, "ms_after_input": round((event["ns"]-action["start_ns"])/1e6, 2)}))
