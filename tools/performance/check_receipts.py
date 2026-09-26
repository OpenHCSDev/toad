"""Check fixture inputs/action sequence and optionally source hashes across captures."""

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("prefixes", type=Path, nargs="+")
parser.add_argument("--same-code", action="store_true")
args = parser.parse_args()
identities, actions, manifests = [], [], []
for prefix in args.prefixes:
    receipt = json.loads(Path(str(prefix) + "-fixture-ready.json").read_text())
    workload = json.loads(Path(str(prefix) + "-actions.json").read_text())
    assert workload["completed"], prefix
    identities.append(receipt["source_sha256"])
    actions.append([action["action"] for action in workload["actions"]])
    manifests.append(json.loads(Path(str(prefix) + "-manifest.json").read_text()))
assert len(set(identities)) == 1, "Fixture source changed"
assert all(sequence == actions[0] for sequence in actions), "Action sequence changed"
if args.same_code:
    for key in ("source_hashes", "framework_hashes", "observer_sha256"):
        assert all(manifest[key] == manifests[0][key] for manifest in manifests), key
print({"captures": len(args.prefixes), "actions_per_capture": len(actions[0]), "source_sha256": identities[0]})
