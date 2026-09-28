"""Bounded trace/action summaries. Inclusive spans overlap and are not additive."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("prefix", type=Path)
parser.add_argument("--slowest", type=int, default=8)
parser.add_argument("--slowest-inputs", type=int, default=0,
                    help="Show overlapping frame work for the worst native key acknowledgments")
parser.add_argument("--gc", action="store_true",
                    help="Show version-bound GC callbacks and first/last tracked-object censuses")
args = parser.parse_args()
trace = json.loads(Path(str(args.prefix) + "-trace.json").read_text())
workload = json.loads(Path(str(args.prefix) + "-actions.json").read_text())
actions = workload["actions"]

def overlaps(event, action):
    return event["ns"] >= action["start_ns"] and event.get("begin_ns", event["ns"]) <= action["end_ns"]

def stats(values):
    values = sorted(values)
    return {"count": len(values), "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[int(.95*(len(values)-1))], 2),
            "p99_ms": round(values[int(.99*(len(values)-1))], 2),
            "max_ms": round(max(values), 2)} if values else {}

selected = [event for event in trace if any(overlaps(event, action) for action in actions)]
groups = defaultdict(list)
for action in actions:
    groups[action["action"].split(":")[0]].extend(event["duration_ms"] for event in trace
        if event["event"] == "loop_gap" and overlaps(event, action))
print(json.dumps({"completed": workload["completed"], "actions": len(actions),
    "overall": {kind: stats([event["duration_ms"] for event in selected if event["event"] == kind])
                for kind in ("loop_gap", "gc", "_refresh_layout", "_compositor_refresh")},
    "anchor_full_geometry": stats([event["duration_ms"] for event in selected
        if event["event"] == "arrange_root" and event.get("visible_only") is False
        and any(caller[0] == "history_anchor.py" for caller in event.get("callers", ()))]),
    "by_action": {kind: stats(values) for kind, values in groups.items()}}, indent=2))
for gap in sorted((event for event in selected if event["event"] == "loop_gap"), key=lambda event:-event["duration_ms"])[:args.slowest]:
    spans = [event for event in trace if event["event"] in {"gc", "_refresh_layout", "_compositor_refresh", "arrange_root"}
             and event["ns"] >= gap["begin_ns"] and event["begin_ns"] <= gap["ns"]]
    print(json.dumps({"gap_ms": gap["duration_ms"], "actions": [action["action"] for action in actions if overlaps(gap, action)],
                      "overlapping_spans": spans}))

for key in sorted((event for event in trace if event["event"] == "prompt_key_applied"
                   and event.get("input_ns") is not None),
                  key=lambda event: -event["acknowledgment_ms"])[:args.slowest_inputs]:
    begin, end = key["input_ns"], key["ns"]
    spans = [{**event, "relative_begin_ms": round((event["begin_ns"] - begin) / 1e6, 3),
              "relative_end_ms": round((event["ns"] - begin) / 1e6, 3)}
             for event in trace if event["event"] in {
                 "gc", "_refresh_layout", "_compositor_refresh", "arrange_root", "navigation_stage"
             } and "begin_ns" in event and event["ns"] >= begin and event["begin_ns"] <= end]
    frames = [{"event": event["event"], "relative_ms": round((event["ns"] - begin) / 1e6, 3),
               "frame": event.get("frame"), "mode": event.get("mode")}
              for event in trace if event["event"] in {"frame_enqueued", "frame_flushed"}
              and begin <= event["ns"] <= end]
    route = [{**event, "relative_ms": round((event["ns"] - begin) / 1e6, 3)}
             for event in trace if event["event"] == "key_route" and event.get("input_ns") == begin]
    print(json.dumps({"key": key, "overlapping_spans": spans,
                      "frames_before_acknowledgment": frames, "route": route}))

if args.gc:
    collections = defaultdict(list)
    for event in selected:
        if event["event"] == "gc":
            collections[event["generation"], event["ui_thread"]].append(event)
    manifest = json.loads(Path(str(args.prefix) + "-manifest.json").read_text())
    census_path = Path(str(args.prefix) + "-census.jsonl")
    censuses = []
    if census_path.exists():
        lines = census_path.read_text().splitlines()
        for line in (lines[:1] + lines[-1:] if len(lines) > 1 else lines):
            census = json.loads(line)
            censuses.append({
                "tracked": census["tracked"],
                "paint_color_cache": census.get("paint_color_cache"),
                "sampled_paint_types": {".".join(name): count for name, count in census["counts"]
                                        if name[0] in {"textual._styles_cache", "textual.strip", "textual.style"}},
                "closed_widgets": census["closed_widgets"],
            })
    print(json.dumps({
        "runtime": manifest.get("runtime"),
        "gc_callbacks": [{"generation": generation, "ui_thread": ui_thread,
                          **stats([event["duration_ms"] for event in events]),
                          "total_ms": round(sum(event["duration_ms"] for event in events), 2),
                          "collected": sum(event["collected"] for event in events),
                          "zero_collected": stats([event["duration_ms"] for event in events
                                                   if not event["collected"]])}
                         for (generation, ui_thread), events in sorted(collections.items())],
        "first_last_census": censuses,
    }, indent=2))
