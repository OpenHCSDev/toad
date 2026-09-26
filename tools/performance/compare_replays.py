"""Compare headless replay setter work and retained watcher ownership."""

import json
from pathlib import Path
import sys

for name in sys.argv[1:]:
    path = Path(name).expanduser()
    report = json.loads((path if path.suffix == ".json" else Path(str(path) + ".json")).read_text())
    print(json.dumps({"capture": name, "completed": report["completed"], "before": report.get("before"),
                      "after": report.get("after"), "filter_costs": [
                          {key: round(action[key], 2) if isinstance(action[key], float) else action[key]
                           for key in ("mode", "category", "setter_ms", "restore_setter_ms", "settled_ms") if key in action}
                          for action in report["actions"] if action["kind"] == "filter"]}, indent=2))
