"""Measure an explicitly selected live Toad process.

--profile-seconds  record a py-spy speedscope profile.
--frame-meter N    time UI work per frame and input-to-paint for N seconds (frame_meter.py).
--targets          write where sidebar thread rows and session tabs are (frame_meter.targets).
"""

import argparse
import json
from pathlib import Path
import subprocess
import time

import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--name", default="live-" + time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--profile-seconds", type=int, default=0)
    parser.add_argument("--rate", type=int, default=100)
    parser.add_argument("--py-spy", default="py-spy")
    parser.add_argument("--gil", action="store_true")
    parser.add_argument("--idle", action="store_true", help="Include samples of threads blocked in calls")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--frame-meter", type=float, default=0)
    parser.add_argument("--targets", action="store_true")
    parser.add_argument("--profile-layout", type=int, default=0, help="Profile the next N calls of --profile-target")
    parser.add_argument("--profile-target", default="textual.screen:Screen._refresh_layout",
                        help="module:Class.method profiled by --profile-layout")
    parser.add_argument("--profile-within", default="",
                        help="Profile --profile-target only inside calls of this module:Class.method (frame_meter.profile_within); "
                             "'slow' profiles every call and keeps those over --profile-min-ms (frame_meter.profile_slow)")
    parser.add_argument("--profile-min-ms", type=float, default=0.0,
                        help="With --profile-within: keep only scopes whose target call took this long (profiled)")
    parser.add_argument("--trace-calls", default="", help="Comma-separated module:Class.method targets to time")
    parser.add_argument("--trace-reflows", action="store_true", help="Record each scoped reflow (frame_meter.trace_reflows)")
    parser.add_argument("--trace-rules", action="store_true", help="Record each style-rule change (frame_meter.trace_rules)")
    parser.add_argument("--trace-exit", action="store_true", help="Record who asks the app to exit (frame_meter.trace_exit)")
    parser.add_argument("--trace-abc", action="store_true", help="Record who grows ABC caches, 40 s (frame_meter.trace_abc_growth)")
    parser.add_argument("--freeze-heap", action="store_true", help="Experiment: freeze the heap now (frame_meter.freeze_heap)")
    parser.add_argument("--heap-census", type=float, default=0,
                        help="After N seconds count the collector's tracked objects by type (frame_meter.heap_census)")
    parser.add_argument("--trace-garbage", action="store_true",
                        help="Count by type what each large collection found, for 12 s (frame_meter.trace_garbage)")
    parser.add_argument("--remeasure", type=int, default=0,
                        help="Arrange the screen at N new widths and time each pass (frame_meter.remeasure)")
    parser.add_argument("--repaint", type=int, default=0,
                        help="Repaint the history viewport N times cold and warm, timing each (frame_meter.repaint)")
    parser.add_argument("--sudo", action="store_true", help="Use non-interactive sudo for attach operations")
    args = parser.parse_args()
    if not (args.profile_seconds > 0 or args.frame_meter > 0 or args.targets or args.profile_layout or args.trace_calls
            or args.trace_reflows or args.trace_rules or args.trace_exit or args.trace_garbage or args.heap_census or args.freeze_heap or args.trace_abc
            or args.remeasure or args.repaint):
        parser.error("Choose --profile-seconds, --frame-meter, --targets or --profile-layout")
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
    privilege = ["sudo", "-n"] if args.sudo else []
    manifest = {"pid": args.pid, "created": created, "executable": process.exe(), "started_ns": time.time_ns()}
    try:
        if args.profile_seconds:
            result = subprocess.run([*privilege, args.py_spy, "record", "--pid", str(args.pid),
                "--duration", str(args.profile_seconds), "--rate", str(args.rate), "--format", "speedscope",
                "--output", str(prefix) + ".speedscope.json", *(["--gil"] if args.gil else []),
                *(["--idle"] if args.idle else []), *(["--native"] if args.native else [])],
                timeout=args.profile_seconds + 30)
            manifest["profile_returncode"] = result.returncode
            result.check_returncode()
        calls = []
        if args.targets:
            calls.append((str(prefix) + "-targets", "targets", ""))
        if args.frame_meter > 0:
            calls.append((str(prefix) + "-frames", "install", f", seconds={args.frame_meter!r}"))
        if args.profile_layout and args.profile_within == "slow":
            calls.append((str(prefix) + "-layout", "profile_slow",
                          f", calls={args.profile_layout!r}, target={args.profile_target!r}, min_ms={args.profile_min_ms!r}"))
        elif args.profile_layout and args.profile_within:
            calls.append((str(prefix) + "-layout", "profile_within",
                          f", calls={args.profile_layout!r}, target={args.profile_target!r}, within={args.profile_within!r}, min_ms={args.profile_min_ms!r}"))
        elif args.profile_layout:
            calls.append((str(prefix) + "-layout", "profile_layout",
                          f", calls={args.profile_layout!r}, target={args.profile_target!r}"))
        if args.trace_calls:
            calls.append((str(prefix) + "-calls", "trace_calls",
                          f", targets={args.trace_calls.split(',')!r}, seconds={max(args.frame_meter, 40)!r}"))
        if args.remeasure:
            calls.append((str(prefix) + "-remeasure", "remeasure", f", iterations={args.remeasure!r}"))
        if args.repaint:
            calls.append((str(prefix) + "-repaint", "repaint", f", iterations={args.repaint!r}"))
        if args.trace_exit:
            calls.append((str(prefix) + "-exit", "trace_exit", ""))
        if args.trace_rules:
            calls.append((str(prefix) + "-rules", "trace_rules", f", seconds={max(args.frame_meter, 40)!r}"))
        if args.trace_abc:
            calls.append((str(prefix) + "-abc", "trace_abc_growth", ""))
        if args.freeze_heap:
            calls.append((str(prefix) + "-freeze", "freeze_heap", ""))
        if args.heap_census:
            calls.append((str(prefix) + "-heap", "heap_census", f", after={args.heap_census!r}"))
        if args.trace_garbage:
            calls.append((str(prefix) + "-garbage", "trace_garbage", ", seconds=150"))
        if args.trace_reflows:
            calls.append((str(prefix) + "-reflows", "trace_reflows", f", seconds={max(args.frame_meter, 40)!r}"))
        if calls:
            assert process.is_running() and process.create_time() == created, "Target process identity changed"
            meter = Path(__file__).resolve().with_name("frame_meter.py")
            entered = str(prefix) + "-remote-entered.json"
            lines = [
                "import importlib.util as _spec_util, json as _json, os as _os, sys as _sys, time as _time",
                f"with open({entered!r}, 'w') as _out: _json.dump({{'pid': _os.getpid(), 'entered_ns': _time.time_ns()}}, _out)",
                # One meter module per process: snapshots record their pauses where the meter reads them.
                "_meter = _sys.modules.get('frame_meter')",
                "if _meter is None:",
                f"    _spec = _spec_util.spec_from_file_location('frame_meter', {str(meter)!r})",
                "    _meter = _sys.modules['frame_meter'] = _spec_util.module_from_spec(_spec)",
                "    _spec.loader.exec_module(_meter)",
                *(f"_meter.{call}(expected_pid={args.pid}, output={output + '.json'!r}{extra})"
                  for output, call, extra in calls),
            ]
            script = Path(str(prefix) + "-remote.py")
            script.write_text("\n".join(lines) + "\n")
            subprocess.run([*privilege, process.exe(), "-c",
                f"import sys; sys.remote_exec({args.pid}, {str(script)!r})"], check=True, timeout=15)
            deadline = time.monotonic() + max(args.frame_meter, 60 if args.profile_layout or args.remeasure or args.repaint else 0) + 20
            outputs = [output + ".json" for output, _call, _extra in calls]
            while time.monotonic() < deadline and not all(Path(path).exists() for path in outputs):
                time.sleep(.1)
            manifest["outputs"] = {path: Path(path).exists() for path in outputs}
            manifest["entered"] = Path(entered).exists()
    finally:
        manifest["finished_ns"] = time.time_ns()
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(manifest_path)


if __name__ == "__main__":
    main()
