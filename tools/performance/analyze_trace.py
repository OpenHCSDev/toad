"""Bounded trace/action summaries. Inclusive spans overlap and are not additive."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
from html import escape
import math

def overlaps(event, action):
    return event["ns"] >= action["start_ns"] and event.get("begin_ns", event["ns"]) <= action["end_ns"]

def stats(values):
    values = sorted(values)
    return {"count": len(values), "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[int(.95*(len(values)-1))], 2),
            "p99_ms": round(values[int(.99*(len(values)-1))], 2),
            "max_ms": round(max(values), 2)} if values else {}


def frame_delivery(trace, actions, *, origin_ns, end_ns, window_seconds=1):
    """Analyze the existing enqueue/writer events, not video capture FPS.

    Empty output and cursor changes may flush. These receipts alone cannot
    establish body motion, emulator paint time, or an input's pixel latency.
    """
    if not math.isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("Frame rate window must be positive and finite")
    frames = sorted((event for event in trace if event["event"] == "frame_flushed"),
                    key=lambda event: event["ns"])
    queued = {event["frame"]: event for event in trace if event["event"] == "frame_enqueued"}
    gaps = [{"start_seconds": (before["ns"] - origin_ns) / 1e9,
             "end_seconds": (after["ns"] - origin_ns) / 1e9,
             "milliseconds": (after["ns"] - before["ns"]) / 1e6,
             "frame": after["frame"], "mode": after["mode"]}
            for before, after in zip(frames, frames[1:])]
    deliveries = [(event["ns"] - queued[event["frame"]]["ns"]) / 1e6
                  for event in frames if event["frame"] in queued]
    window_ns = round(window_seconds * 1e9)
    rolling = []
    left = right = 0
    for end in range(origin_ns + window_ns, end_ns + window_ns, window_ns):
        end = min(end, end_ns)
        begin = max(origin_ns, end - window_ns)
        while right < len(frames) and frames[right]["ns"] < end:
            right += 1
        while left < right and frames[left]["ns"] < begin:
            left += 1
        elapsed = (end - begin) / 1e9
        if elapsed:
            rolling.append({"start_seconds": (begin-origin_ns)/1e9,
                            "end_seconds": (end-origin_ns)/1e9,
                            "writer_receipts": right-left, "rate_hz": (right-left)/elapsed})
    phases = []
    for action in actions:
        within = [gap["milliseconds"] for gap in gaps
                  if origin_ns + gap["start_seconds"] * 1e9 >= action["start_ns"]
                  and origin_ns + gap["end_seconds"] * 1e9 <= action["end_ns"]]
        phases.append({"action": action["action"], "intervals": stats(within),
                       "writer_receipts": sum(action["start_ns"] <= frame["ns"] < action["end_ns"]
                                              for frame in frames)})
    return {"clock": "time.monotonic_ns from sidebar_validation_driver.record",
            "origin_ns": origin_ns, "observed_end_ns": end_ns,
            "scope": "Native writer completion; not changed pixels or terminal presentation FPS. "
                     "Zero stationary motion is legitimate, not a stall classification.",
            "flushed_frames": len(frames),
            "unmatched_enqueues": len(set(queued)-{event["frame"] for event in frames}),
            "intervals": stats([gap["milliseconds"] for gap in gaps]),
            "enqueue_to_writer": stats(deliveries), "phases": phases,
            "rolling": rolling, "gaps": gaps}


def write_frame_timeline(output, delivery):
    """Write a readable delivery-rate/gap chart alongside its original trace."""
    output = Path(output)
    output.write_text(json.dumps(delivery, indent=2) + "\n")
    points = delivery["rolling"]
    duration = max((delivery["observed_end_ns"] - delivery["origin_ns"]) / 1e9, .001)
    rate_max = max((point["rate_hz"] for point in points), default=1) or 1
    gap_max = max((gap["milliseconds"] for gap in delivery["gaps"]), default=1) or 1
    x = lambda seconds: 70 + seconds/duration*1000
    rates = " ".join(f"{x(p['end_seconds']):.2f},{200-p['rate_hz']/rate_max*120:.2f}" for p in points)
    gaps = " ".join(f"{x(g['end_seconds']):.2f},{380-g['milliseconds']/gap_max*120:.2f}"
                    for g in delivery["gaps"])
    summary = delivery["intervals"]
    caption = escape(f"Writer intervals (ms): {summary}; stationary gaps are not classified as stalls")
    output.with_suffix(".svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="470" viewBox="0 0 1120 470">'
        '<rect width="1120" height="470" fill="white"/>'
        '<g font-family="sans-serif" font-size="14" fill="#222">'
        '<text x="70" y="25">Application delivery over time (native writer receipts, not recorded FPS)</text>'
        f'<text x="70" y="60">Rolling writer rate, peak {rate_max:.1f} Hz</text>'
        f'<text x="70" y="245">Writer interval, peak {gap_max:.1f} ms</text>'
        f'<text x="70" y="410">0 → {duration:.2f} seconds since recording launch; same monotonic domain as input/profile</text>'
        f'<text x="70" y="440">{caption}</text></g>'
        '<path d="M70 80V200H1070 M70 260V380H1070" stroke="#aaa" fill="none"/>'
        f'<polyline points="{rates}" stroke="#2374ab" fill="none"/>'
        f'<polyline points="{gaps}" stroke="#bd491e" fill="none"/></svg>\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix", type=Path)
    parser.add_argument("--slowest", type=int, default=8)
    parser.add_argument("--slowest-inputs", type=int, default=0,
                        help="Show overlapping frame work for the worst native key acknowledgments")
    parser.add_argument("--gc", action="store_true",
                        help="Show version-bound GC callbacks and first/last tracked-object censuses")
    parser.add_argument("--frame-window-seconds", type=float, default=1,
                        help="Window for the existing frame writer rate timeline")
    args = parser.parse_args()
    trace = json.loads(Path(str(args.prefix) + "-trace.json").read_text())
    workload = json.loads(Path(str(args.prefix) + "-actions.json").read_text())
    actions = workload["actions"]
    if trace and actions:
        delivery = frame_delivery(trace, actions, origin_ns=actions[0]["start_ns"],
                                  end_ns=actions[-1]["end_ns"],
                                  window_seconds=args.frame_window_seconds)
        write_frame_timeline(Path(str(args.prefix) + "-frame-delivery.json"), delivery)

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


if __name__ == "__main__":
    main()
