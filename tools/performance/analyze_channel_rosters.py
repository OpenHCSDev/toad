"""Check observed native channel row identities across captured tab revisits."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("prefix", type=Path)
args = parser.parse_args()
workload = json.loads(Path(str(args.prefix) + "-actions.json").read_text())
identities = defaultdict(set)
observations = defaultdict(int)
for snapshot in workload["snapshots"]:
    for row in snapshot["widgets"]:
        if row.get("row_kind") in {"channel", "irc"}:
            key = snapshot["mode"], row["row_kind"], row["target"]
            identities[key].add(row["object_id"])
            observations[key] += 1
changed = [list(key) for key, values in identities.items() if len(values) > 1]
print(json.dumps({
    "completed": workload["completed"], "actions": len(workload["actions"]),
    "modes_with_channels": len({key[0] for key in identities}),
    "repeated_channel_keys": sum(count > 1 for count in observations.values()),
    "changed_channel_identities": changed,
}, indent=2))
assert workload["completed"] and identities and not changed
