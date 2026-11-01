"""Read-only py-spy capture of an explicit live PID on an isolated display.

In-process observations belong to physical_ui.TerminalApp's startup lifetime.
This command never injects frame meters, callbacks, heap changes or UI input.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from agent_comms.child_process import ProcessIdentity
from agent_comms.nominal.field_codec import FieldCodec

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from physical_ui import XvfbDisplay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--display", required=True, help="Explicit owned isolated Xvfb display")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--name", default="live-" + time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--profile-seconds", type=int, required=True)
    parser.add_argument("--rate", type=int, default=100)
    parser.add_argument("--py-spy", default="py-spy")
    parser.add_argument("--gil", action="store_true")
    parser.add_argument("--idle", action="store_true")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--sudo", action="store_true", help="Non-interactive sudo for read-only py-spy only")
    args = parser.parse_args()
    if args.profile_seconds <= 0 or args.rate <= 0:
        parser.error("Profile duration and sampling rate must be positive")
    if Path(args.name).name != args.name:
        parser.error("--name must be a capture basename")
    args.output_dir = args.output_dir.expanduser().resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.output_dir / args.name
    manifest_path = Path(str(prefix) + "-manifest.json")
    profile_path = Path(str(prefix) + ".speedscope.json")
    if manifest_path.exists() or profile_path.exists():
        parser.error("Choose a fresh capture name")
    identity = ProcessIdentity.capture(args.pid)
    manifest = {"process": FieldCodec.encode(identity), "started_ns": time.time_ns(),
                "executable": str(Path(f"/proc/{identity.pid}/exe").resolve(strict=True))}
    privilege = ["sudo", "-n"] if args.sudo else []
    try:
        with XvfbDisplay(args.display) as display:
            manifest["display"] = display.name
            result = subprocess.run(
                [*privilege, args.py_spy, "record", "--pid", str(identity.pid),
                 "--duration", str(args.profile_seconds), "--rate", str(args.rate),
                 "--format", "speedscope", "--output", str(profile_path),
                 *(["--gil"] if args.gil else []), *(["--idle"] if args.idle else []),
                 *(["--native"] if args.native else [])],
                timeout=args.profile_seconds + 30,
            )
            manifest["profile_returncode"] = result.returncode
            result.check_returncode()
            if not identity.alive():
                raise RuntimeError("The selected process birth ended during profiling")
    finally:
        manifest["finished_ns"] = time.time_ns()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(manifest_path)


if __name__ == "__main__":
    main()
