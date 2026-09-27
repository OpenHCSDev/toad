"""Summarize diagnostic measurement calls; recursive timings overlap, not additive."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("prefix", type=Path)
parser.add_argument("--limit", type=int, default=15)
args = parser.parse_args()
events = json.loads(Path(str(args.prefix) + "-trace.json").read_text())
actions = json.loads(Path(str(args.prefix) + "-actions.json").read_text())["actions"]
selected = [event for event in events if event["event"] == "box_model"
            and any(action["start_ns"] <= event["ns"] <= action["end_ns"] for action in actions)]
classes = defaultdict(Counter)
variants = defaultdict(list)
for event in selected:
    count = classes[event["widget"]]
    count["calls"] += 1
    count["hits" if event["hit"] else "misses"] += 1
    count["inclusive_ms"] += event["duration_ms"]
    if not event["hit"]:
        variants[event["owner"], tuple(event["revision"]), tuple(event["result"])].append(event)
duplicates = [rows for rows in variants.values() if len(rows) > 1]
print(json.dumps({"calls": len(selected), "classes": [
    {"widget": widget, **counts} for widget, counts in sorted(
        classes.items(), key=lambda item: -item[1]["inclusive_ms"])[:args.limit]],
    "same_revision_result_multiple_misses": [{
        "widget": rows[0]["widget"], "owner": rows[0]["owner"], "result": rows[0]["result"],
        "calls": len(rows), "containers": [row["container"] for row in rows],
        "height_fractions": [row["height_fraction"] for row in rows],
        "inclusive_ms": sum(row["duration_ms"] for row in rows),
    } for rows in sorted(duplicates, key=lambda rows: -sum(row["duration_ms"] for row in rows))[:args.limit]]}, indent=2))
