"""Summarize native widget owners from a diagnostic census without collecting GC."""

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("prefix", type=Path)
parser.add_argument("--initial", action="store_true")
args = parser.parse_args()
lines = Path(str(args.prefix) + "-census.jsonl").read_text().splitlines()
census = json.loads(lines[0 if args.initial else -1])
print(json.dumps({"tracked": census["tracked"], **census["widget_cohorts"]}, indent=2))
