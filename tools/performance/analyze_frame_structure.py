"""Summarize structural navigation probes without treating nested spans as totals."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median


def summarize(path: Path, *, detail: bool = False) -> dict:
    data = json.loads(path.read_text())
    phases = defaultdict(list)
    for row in data["returns"]:
        phases[row["phase"]].append(row)
    report = {
        "capture": path.name,
        "fixture": {key: data.get(key) for key in
                    ("empty", "tabs", "source_threads", "history_records", "peers", "channels")},
        "instrumentation": data.get("instrumentation"),
        "observation_only": data.get("observation_only", False),
        "phases": [], "ownership": [],
    }
    for phase, rows in phases.items():
        mounts = Counter()
        operations = defaultdict(list)
        for row in rows:
            mounts.update(row["mounts"])
            for event in row.get("timed_events", ()):
                operation = event["operation"]
                if work_type := event.get("work_type"):
                    operation += f":{work_type}"
                operations[operation].append(event["duration_ms"])
        summary = {
            "phase": phase, "switches": len(rows),
            "switch_median_ms": round(median(row["switch_ms"] for row in rows), 2),
            "switch_max_ms": max(row["switch_ms"] for row in rows),
            "switches_over_50ms": sum(row["switch_ms"] > 50 for row in rows),
            "switches_over_100ms": sum(row["switch_ms"] > 100 for row in rows),
            "loop_gap_max_ms": max(row["max_loop_gap_ms"] for row in rows),
            "switches_with_loop_gap_over_100ms": sum(row["max_loop_gap_ms"] > 100 for row in rows),
            "gc_max_ms": max(row.get("gc_max_ms", 0) for row in rows) if data.get("gc_observation") else None,
            "display_median_ms": round(median(row["headless_display_ms"] for row in rows), 2),
            "reflows_median": median(row["reflows"] for row in rows),
            "styled_nodes_median": median(row["styled_nodes"] for row in rows),
            "changed_rule_maps_median": (median(row["changed_native_style_rule_maps"] for row in rows)
                                         if rows[0].get("changed_native_style_rule_maps") is not None else None),
            "mounted_widgets": dict(mounts),
            "stale_reflows": sum(row["stale_roster_reflows"] for row in rows),
            "discarded_renders": sum(row["discarded_navigation_renders"] for row in rows),
        }
        if detail:
            summary["inclusive_call_spans_not_additive"] = {
                name: {"calls": len(values), "median_ms": round(median(values), 2), "max_ms": max(values)}
                for name, values in sorted(operations.items())
            }
        report["phases"].append(summary)
    for census in data.get("ownership_censuses", ()):
        classes = census["registered_types"]
        report["ownership"].append({
            "phase": census["phase"], "tracked": census["tracked"],
            "widgets": census["registered_widgets"], "active_widgets": census["active_registered_widgets"],
            "tab_strips": classes.get("SessionsTabs", 0), "labels": classes.get("SessionLabel", 0),
            "close_buttons": classes.get("SessionTabClose", 0), "footers": classes.get("Footer", 0),
            "channel_panels": classes.get("ChannelsSidebar", 0),
            "fragment_views": classes.get("TranscriptFragmentView", 0),
            "conversations": classes.get("Conversation", 0),
            "editors": classes.get("PromptTextArea", 0),
            "right_sidebars": classes.get("SideBar", 0),
            "preparation": census["preparation"],
        })
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path, nargs="+")
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()
    for path in args.captures:
        print(json.dumps(summarize(path, detail=args.detail), indent=2))
