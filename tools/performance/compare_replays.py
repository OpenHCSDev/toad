"""Compare headless replay setter work and retained watcher ownership."""

import json
from pathlib import Path
import sys
import statistics


def summary(values):
    values = sorted(values)
    return {"count": len(values), "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[int(.95 * (len(values) - 1))], 2),
            "p99_ms": round(values[int(.99 * (len(values) - 1))], 2),
            "max_ms": round(max(values), 2)} if values else {}

for name in sys.argv[1:]:
    path = Path(name).expanduser()
    report = json.loads((path if path.suffix == ".json" else Path(str(path) + ".json")).read_text())
    observed = report.get("observation", {})
    print(json.dumps({"capture": name,
                      "spinners": report.get("spinners", []),
                      "gc": summary([item["wall_ms"] for item in observed.get("gc", [])]),
                      "loop_gaps": summary([item["wall_ms"] for item in observed.get("loop_gaps", [])]),
                      "slowest_gc": sorted(observed.get("gc", []), key=lambda row: -row["wall_ms"])[:3],
                      "slowest_setters": sorted(observed.get("spans", []), key=lambda row: -row["wall_ms"])[:3]}, indent=2))
    print(json.dumps({"capture": name, "completed": report["completed"], "before": report.get("before"),
                      "after": report.get("after"), "filter_costs": [
                          {key: round(action[key], 2) if isinstance(action[key], float) else action[key]
                           for key in ("mode", "category", "setter_ms", "restore_setter_ms", "settled_ms") if key in action}
                          for action in report["actions"] if action["kind"] == "filter"]}, indent=2))
