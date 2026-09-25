"""Package a py-spy capture without transcript content or machine-local paths.

The optional action-to-profile alignment uses profiler launch time, not an exact
first-sample handshake. Observer durations use their own exact monotonic spans.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import statistics


def portable(file):
    for marker, prefix in (("/src/toad/", "toad/"), ("/src/textual/", "textual/"),
                           ("/site-packages/", "site-packages/"),
                           ("/lib/python3.14/", "python3.14/")):
        if marker in file:
            return prefix + file.split(marker, 1)[1]
    return Path(file).name if file.startswith("/") else file


def stats(values):
    values = sorted(values)
    return {"count": len(values), "median_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[int(.95 * (len(values)-1))], 2),
            "max_ms": round(values[-1], 2)} if values else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    trace = json.loads(args.trace.read_text())
    workload = json.loads(args.actions.read_text())
    assert workload["completed"]
    frames = profile["shared"]["frames"]
    for frame in frames:
        if "file" in frame:
            frame["file"] = portable(frame["file"])
    for thread in profile["profiles"]:
        thread["name"] = thread["name"].partition('"')[2].rstrip('"') or "unknown"
    profile.pop("name", None)
    raw = json.dumps(profile, separators=(",", ":")).encode()
    destination = args.output_dir
    assert destination.is_dir()
    artifact = destination / "navigation.speedscope.json.gz"
    artifact.write_bytes(gzip.compress(raw, mtime=0))
    main_thread = next(p for p in profile["profiles"] if p["name"] == "MainThread")
    actions = workload["actions"]
    origin = workload["profile_request_ns"]
    samples = []
    clock = main_thread["startValue"]
    for stack, weight in zip(main_thread["samples"], main_thread["weights"]):
        samples.append((clock, clock + weight, stack))
        clock += weight
    details = []
    for index, action in enumerate(actions):
        start, end = (action["start_ns"]-origin)/1e9, (action["end_ns"]-origin)/1e9
        matching = [e for e in trace if e["ns"] >= action["start_ns"]
                    and e.get("begin_ns", e["ns"]) <= action["end_ns"]]
        counts = Counter()
        for a, b, stack in samples:
            weight = max(0, min(b, end) - max(a, start))
            if weight:
                for identity in {(frames[i].get("file", ""), frames[i]["name"]) for i in stack}:
                    counts[identity] += weight
        roots = {"run", "run_forever", "run_until_complete", "_run_once", "_run",
                 "invoke", "_invoke", "main", "acp", "__call__", "<module>",
                 "_process_messages_loop", "_dispatch_message", "_on_message", "_process_messages"}
        details.append({"index": index, "kind": action["action"].split(":")[0],
                        "start_s": round(start, 6), "end_s": round(end, 6),
                        "timings": {kind: stats([e["duration_ms"] for e in matching if e["event"] == kind])
                                    for kind in ("loop_gap", "_refresh_layout", "_compositor_refresh", "gc")},
                        "approximate_inclusive_samples": [
                            {"file": file, "function": name, "seconds": round(weight, 3)}
                            for (file, name), weight in counts.most_common()
                            if name not in roots][:20]})
    output = {"completed": True, "actions": len(actions), "cells": workload["snapshots"][0]["size"],
              "pixels": workload.get("pixels"), "display": "isolated Xvfb",
              "sample_rate_hz": 100, "idle_included": True, "profile_seconds": clock,
              "sample_count": sum(len(p["samples"]) for p in profile["profiles"]),
              "sha256_gzip": hashlib.sha256(artifact.read_bytes()).hexdigest(),
              "alignment": "Approximate sample alignment from profiler launch; attach offset not measured. Observer timings are monotonic wall spans, not pixels. Inclusive samples overlap.",
              "per_action": details}
    (destination / "actions.json").write_text(json.dumps(output, indent=2) + "\n")
    print({key: value for key, value in output.items() if key != "per_action"})


if __name__ == "__main__":
    main()
