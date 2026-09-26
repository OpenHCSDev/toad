"""Filter stress coverage, draft retention, and native key acknowledgment."""

from collections import Counter
import json
from pathlib import Path
import statistics
import sys

for name in sys.argv[1:]:
    base = Path(name).expanduser()
    workload = json.loads(Path(str(base) + "-actions.json").read_text())
    trace = json.loads(Path(str(base) + "-trace.json").read_text())
    inputs = [event for event in trace if event["event"] == "input_key" and event["key"] == "x"]
    applied = [event for event in trace if event["event"] == "prompt_key_applied"]
    latencies = sorted(event["acknowledgment_ms"] for event in applied if event.get("acknowledgment_ms") is not None)
    snapshot = json.loads(Path(str(base) + "-state.json").read_text())
    print(json.dumps({"capture": name, "completed": workload["completed"], "error": workload.get("error"),
                      "actions": len(workload["actions"]), "last_actions": [a["action"] for a in workload["actions"][-8:]],
                      "verification": workload.get("filter_verification"), "input_keys": len(inputs),
                      "applied_keys": len(applied), "key_modes": dict(Counter(e["mode"] for e in applied)),
                      "input_acknowledgment": {"count":len(latencies), "median_ms": round(statistics.median(latencies),2),
                          "p95_ms":round(latencies[int(.95*(len(latencies)-1))],2), "max_ms":round(max(latencies),2)} if latencies else {},
                      "last_view": snapshot.get("conversation")}, indent=2))
