"""Save profiles and optional DTO/SVG state from an explicitly selected live PID."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--name", default="live-" + time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--profile-seconds", type=int, default=0)
    parser.add_argument("--rate", type=int, default=100)
    parser.add_argument("--py-spy", default="py-spy")
    parser.add_argument("--gil", action="store_true")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--state", action="store_true", help="Export loaded DTOs using CPython 3.14 remote_exec")
    parser.add_argument("--screen", action="store_true", help="Export through Textual's screenshot API")
    parser.add_argument("--sudo", action="store_true", help="Use non-interactive sudo for attach operations")
    args = parser.parse_args()
    if not (args.profile_seconds > 0 or args.state or args.screen):
        parser.error("Choose --profile-seconds, --state, or --screen")
    if Path(args.name).name != args.name:
        parser.error("--name must be a capture basename")
    args.output_dir = args.output_dir.expanduser().resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.output_dir / args.name
    manifest_path = Path(str(prefix) + "-manifest.json")
    if manifest_path.exists():
        parser.error("Choose a fresh capture name")
    process = psutil.Process(args.pid)
    created = process.create_time()
    executable = process.exe()
    privilege = ["sudo", "-n"] if args.sudo else []
    manifest = {"pid": args.pid, "created": created, "executable": executable,
                "rss_before": process.memory_info().rss, "started_ns": time.time_ns(),
                "profile_seconds": args.profile_seconds, "gil_only": args.gil, "native": args.native}
    try:
        if args.profile_seconds:
            result = subprocess.run([*privilege, args.py_spy, "record", "--pid", str(args.pid),
                "--duration", str(args.profile_seconds), "--rate", str(args.rate), "--format", "speedscope",
                "--output", str(prefix) + ".speedscope.json", *(["--gil"] if args.gil else []),
                *(["--native"] if args.native else [])], timeout=args.profile_seconds+30)
            manifest["profile_returncode"] = result.returncode
            result.check_returncode()
        if args.state or args.screen:
            assert process.is_running() and process.create_time() == created, "Target process identity changed"
            tools = Path(__file__).resolve().parent
            script = Path(str(prefix) + "-remote.py")
            lines = ["import importlib.util as _capture_import"]
            receipts = []
            for enabled, module, suffix in ((args.state, "capture_state", "state"), (args.screen, "capture_screen", "screen")):
                if not enabled:
                    continue
                output = str(prefix) + "-" + suffix
                lines.extend((
                    f"_spec = _capture_import.spec_from_file_location({module!r}, {str(tools / (module + '.py'))!r})",
                    "_module = _capture_import.module_from_spec(_spec)",
                    "_spec.loader.exec_module(_module)",
                    f"_module.capture(expected_pid={args.pid}, output_prefix={output!r})",
                ))
                receipts.append(output)
            fd = os.open(script, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as output:
                output.write("\n".join(lines) + "\n")
            subprocess.run([*privilege, executable, "-c",
                f"import sys; sys.remote_exec({args.pid}, {str(script)!r})"], check=True, timeout=15)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not all(
                    Path(path + ".json").exists() or Path(path + "-error.json").exists() for path in receipts):
                time.sleep(.1)
            manifest["receipts"] = {path: ("complete" if Path(path + ".json").exists() else
                "error" if Path(path + "-error.json").exists() else "pending") for path in receipts}
    finally:
        manifest["finished_ns"] = time.time_ns()
        fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(manifest, output, indent=2)
        print(manifest_path)


if __name__ == "__main__":
    main()
