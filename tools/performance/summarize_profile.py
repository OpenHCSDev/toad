"""Summarize sampled Python stacks; GIL-only weights are not a wall timeline."""

import argparse
from collections import Counter
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("profile", type=Path)
parser.add_argument("--thread", default="MainThread")
parser.add_argument("--include-native", action="store_true")
parser.add_argument("--limit", type=int, default=25)
args = parser.parse_args()
data = json.loads(args.profile.read_text())
frames = data["shared"]["frames"]
for profile in data["profiles"]:
    if profile.get("type") != "sampled" or args.thread not in profile.get("name", ""):
        continue
    inclusive, leaf = Counter(), Counter()
    weights = profile.get("weights", [1] * len(profile["samples"]))
    total = sum(weights)
    for stack, weight in zip(profile["samples"], weights):
        selected = [frames[index] for index in stack if args.include_native or
                    frames[index].get("file", "").endswith(".py") or frames[index].get("file", "").startswith("<")]
        keys = [(frame.get("file", ""), frame["name"]) for frame in selected]
        for key in set(keys):
            inclusive[key] += weight
        if keys:
            leaf[keys[-1]] += weight
    def rows(counter):
        return [{"file": key[0], "function": key[1], "sample_share_percent": round(100*weight/total, 2)}
                for key, weight in counter.most_common(args.limit)] if total else []
    print(json.dumps({"thread": profile["name"], "samples": len(profile["samples"]),
                      "inclusive_overlapping": rows(inclusive), "leaf": rows(leaf)}, indent=2))
