#!/usr/bin/env python3
"""Record real installed terminal output without touching the desktop display."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import re
from pathlib import Path
import select
import secrets
import shutil
import shlex
import signal
import subprocess
import sys
import time


def process_table():
    """Read Linux process identities; start ticks protect against PID reuse."""
    table = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            table[int(path.parent.name)] = (int(fields[1]), int(fields[3]), int(fields[19]), fields[0])
        except (OSError, ValueError, IndexError):
            continue  # Processes can exit while /proc is being read.
    return table


@dataclass
class OwnedProcess:
    process: subprocess.Popen
    identities: dict[int, int]

    def members(self):
        table = process_table()
        owned = {pid for pid, (_, sid, ticks, _) in table.items()
                 if sid == self.process.pid or self.identities.get(pid) == ticks}
        leader = table.get(self.process.pid)
        if leader is not None and self.identities.get(self.process.pid, leader[2]) != leader[2]:
            # This PID now belongs to a different process, so its new session
            # and descendants are outside recorder ownership.
            owned = {pid for pid in owned if self.identities.get(pid) == table[pid][2]}
        # Include children that created their own sessions (e.g. native workers).
        while True:
            children = {pid for pid, (parent, _, _, _) in table.items() if parent in owned}
            if children <= owned:
                break
            owned |= children
        for pid in owned:
            self.identities[pid] = table[pid][2]
        return {pid: table[pid] for pid in owned if table[pid][3] != "Z"}

    def send_signal(self, sig):
        for pid, (_, _, ticks, _) in self.members().items():
            if process_table().get(pid, (0, 0, -1, ""))[2] == ticks:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass

    def stop(self, sig=signal.SIGTERM):
        self.send_signal(sig)
        deadline = time.monotonic() + 3
        while self.members() and time.monotonic() < deadline:
            self.process.poll()
            time.sleep(.05)
        if self.members():
            self.send_signal(signal.SIGKILL)
        self.process.wait(timeout=3)
        deadline = time.monotonic() + 2
        while self.members() and time.monotonic() < deadline:
            time.sleep(.05)
        return sorted(self.members())


class ProcessOwner:
    """One launcher/timeout/cleanup mechanism for all recorder subprocesses."""

    def __init__(self):
        self.children = []

    def start(self, argv, **kwargs):
        process = subprocess.Popen(argv, start_new_session=True, **kwargs)
        owned = OwnedProcess(process, {})
        owned.members()
        self.children.append(owned)
        return owned

    def run(self, argv, env, *, timeout=30, stdout=subprocess.DEVNULL, **kwargs):
        owned = self.start(argv, env=env, stdout=stdout, **kwargs)
        try:
            out, err = owned.process.communicate(timeout=timeout)
            if owned.process.returncode:
                raise subprocess.CalledProcessError(owned.process.returncode, argv, out, err)
            return subprocess.CompletedProcess(argv, owned.process.returncode, out, err)
        finally:
            owned.stop()

    def cleanup(self):
        leaks, errors = [], []
        for owned in reversed(self.children):
            try:
                leaks.extend(owned.stop())
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        return {"remaining_owned_pids": sorted(set(leaks)), "errors": errors,
                "processes": [{"pid": o.process.pid, "returncode": o.process.returncode,
                               "identities": o.identities} for o in self.children]}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_probe():
    """Executed by the selected runtime interpreter, without loading the app."""
    result = {"python": sys.executable, "prefix": sys.prefix, "packages": {}}
    for name in ("toad", "textual", "agent_comms"):
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            result["packages"][name] = {"error": "module not installed"}
            continue
        origin = Path(spec.origin).resolve()
        files = sorted(origin.parent.rglob("*.py"))
        fingerprint = hashlib.sha256()
        for path in files:
            fingerprint.update(str(path.relative_to(origin.parent)).encode())
            fingerprint.update(bytes.fromhex(digest(path)))
        package = {"origin": str(origin), "module_sha256": digest(origin),
                   "source_tree_sha256": fingerprint.hexdigest()}
        # Distribution names are discovered from Python's own package metadata.
        for distribution in importlib.metadata.packages_distributions().get(name, []):
            dist = importlib.metadata.distribution(distribution)
            package["distribution"] = distribution
            package["version"] = dist.version
            direct = dist.read_text("direct_url.json")
            if direct:
                package["direct_url"] = json.loads(direct)
        result["packages"][name] = package
    return result


@dataclass(frozen=True)
class RuntimeSelection:
    launcher: Path
    bin_directory: Path
    selection: str

    @classmethod
    def from_environment(cls, command, env):
        launcher = Path(shutil.which(command[0]) or command[0]).resolve()
        if Path(command[0]).name != "toad-comms":
            raise ValueError("Use the installed toad-comms entrypoint (optional thread argument)")
        runtime = env.get("AGENT_COMMS_RUNTIME_ROOT")
        if runtime:
            return cls(launcher, Path(runtime).expanduser().absolute(), "AGENT_COMMS_RUNTIME_ROOT")
        acp = env.get("AGENT_COMMS_ACP_LAUNCHER") or shutil.which("agent-comms-acp")
        acp = acp or str(Path.home() / ".local/bin/agent-comms-acp")
        return cls(launcher, Path(acp).resolve().parent,
                   "AGENT_COMMS_ACP_LAUNCHER" if env.get("AGENT_COMMS_ACP_LAUNCHER") else "PATH agent-comms-acp")

    def receipt(self, owner, env):
        result = {"selection": self.selection, "bin_directory": str(self.bin_directory.resolve()),
                  "launcher": str(self.launcher), "launcher_sha256": digest(self.launcher)}
        result["entrypoints"] = {name: {"path": str((self.bin_directory / name).resolve()),
                                       "sha256": digest(self.bin_directory / name)}
                                 for name in ("toad", "agent-comms-acp")}
        activation = self.bin_directory.parent / "activation.json"
        if activation.is_file():
            result["activation_path"] = str(activation.resolve())
            result["activation_sha256"] = digest(activation)
            result["activation"] = json.loads(activation.read_text())
        probe = owner.run([str(self.bin_directory / "python"), str(Path(__file__).resolve()),
                           "--runtime-probe"], env, stdout=subprocess.PIPE, text=True, timeout=15)
        result["observed"] = json.loads(probe.stdout)
        return result


def artifacts(output, args, env, owner, *, start, seconds, label=None):
    video = output / "terminal.mp4"
    common = ["ffmpeg", "-nostdin", "-y", "-loglevel", "warning", "-threads", "1",
              "-filter_threads", "1", "-filter_complex_threads", "1"]
    interval = ["-ss", str(start), "-t", str(seconds), "-i", str(video)]
    slow = output / (f"{label}-slow.mp4" if label else "slow.mp4")
    sheet = output / (f"{label}-frames.png" if label else "frames.png")
    owner.run(common + interval + [
        "-vf", f"setpts={args.slowdown}*(PTS-STARTPTS)", "-r", str(args.fps),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-threads", "1",
        str(slow),
    ], env, timeout=60)
    frames = min(args.review_frames, max(1, math.ceil(seconds * args.review_fps)))
    rows = math.ceil(frames / args.sheet_columns)
    # Input seeking resets PTS. Add the source offset before drawing timestamps.
    stamp = r"drawtext=text='%{pts\:hms}':fontsize=14:fontcolor=white:box=1:boxcolor=black:x=4:y=4"
    filters = (f"fps={args.review_fps},settb=AVTB,setpts=PTS+{start}/TB,{stamp},"
               f"scale=640:-2,tile={args.sheet_columns}x{rows}:nb_frames={frames}")
    owner.run(common + interval + ["-vf", filters, "-frames:v", "1", "-threads", "1",
                                  "-update", "1", str(sheet)], env, timeout=60)


def record(args):
    output = args.output.expanduser().resolve()
    scratch = (Path.home() / ".cache/agent-scratch").resolve()
    if not output.is_relative_to(scratch):
        raise ValueError(f"Recording output must be under {scratch}")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    command = command or ["toad-comms"]
    required = ("Xvfb", "st", "xdotool", "ffmpeg", "ffprobe", "import", command[0])
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"Missing programs: {', '.join(missing)}")
    env = os.environ.copy()
    env.pop("DISPLAY", None)
    env.pop("NO_COLOR", None)
    env.pop("PYTHONPATH", None)  # The installed toad-comms launcher also clears it.
    selection = RuntimeSelection.from_environment(command, env)
    # Pin the selection before a concurrently changed launcher symlink can redirect it.
    env["AGENT_COMMS_RUNTIME_ROOT"] = str(selection.bin_directory.resolve())
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "owner": args.owner, "purpose": "installed TUI physical interaction video review",
        "output": str(output), "command": command, "terminal_command": ["st", "-e", *command],
        "fps": args.fps, "screen": [args.width, args.height],
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "assessment": "unreviewed", "capture_completed": False, "completed": False,
        "review": {"start_seconds": args.review_start, "seconds": args.review_seconds,
                   "fps": args.review_fps, "frames_limit": args.review_frames,
                   "slowdown": args.slowdown, "timestamp_basis": "source video seconds"},
    }
    env["TOAD_VIDEO_OUTPUT"] = str(output)
    env["TOAD_VIDEO_MARK_SNAPSHOTS"] = "1"
    owner = ProcessOwner()
    capture = terminal = None
    window = None
    try:
        with ExitStack() as stack:
            receipt["runtime_before"] = selection.receipt(owner, env)
            display_number = next((number for number in (secrets.randbelow(9000) + 100 for _ in range(100))
                                   if not Path(f"/tmp/.X{number}-lock").exists()
                                   and not Path(f"/tmp/.X11-unix/X{number}").exists()), None)
            if display_number is None:
                raise RuntimeError("No unused isolated display found")
            read_fd, write_fd = os.pipe()
            try:
                xvfb = owner.start([
                    "Xvfb", f":{display_number}", "-displayfd", str(write_fd), "-screen", "0",
                    f"{args.width}x{args.height}x24", "-nolisten", "tcp",
                ], pass_fds=(write_fd,), stderr=stack.enter_context((output / "xvfb.log").open("w")))
            finally:
                os.close(write_fd)
            with os.fdopen(read_fd) as pipe:
                if not select.select([pipe], [], [], 10)[0]:
                    raise TimeoutError("Virtual display did not start")
                number = os.read(pipe.fileno(), 32).decode().strip()
            if not number.isdecimal() or int(number) != display_number:
                raise RuntimeError("Virtual display returned no safe display number")
            env["DISPLAY"] = ":" + number
            receipt["display"] = env["DISPLAY"]
            terminal = owner.start(["st", "-e", *command], env=env,
                                  stderr=stack.enter_context((output / "terminal.log").open("w")))
            window = owner.run(["xdotool", "search", "--sync", "--pid", str(terminal.process.pid)], env,
                               stdout=subprocess.PIPE, timeout=10, text=True).stdout.splitlines()[0]
            owner.run(["xdotool", "windowfocus", "--sync", window], env)
            if args.fit_window:
                owner.run(["xdotool", "windowsize", window, str(args.width - 20), str(args.height - 20)], env)
            receipt["window"] = window
            capture = owner.start([
                "ffmpeg", "-nostdin", "-y", "-loglevel", "warning", "-threads", "1", "-f", "x11grab",
                "-framerate", str(args.fps), "-video_size", f"{args.width}x{args.height}",
                "-i", env["DISPLAY"], "-t", str(args.max_duration), "-c:v", "libx264", "-preset", "ultrafast",
                "-crf", "26", "-threads", "1", "-r", str(args.fps), "-fps_mode", "cfr", "-pix_fmt", "yuv420p", str(output / "terminal.mp4"),
            ], stderr=stack.enter_context((output / "capture.log").open("w")))
            started = time.monotonic()
            deadline = started + args.max_duration
            env["TOAD_VIDEO_EPOCH"] = str(started)
            print(f"Recording isolated display {env['DISPLAY']}: {output}", flush=True)

            def remaining():
                seconds = deadline - time.monotonic()
                if seconds <= 0:
                    raise TimeoutError("Recording interaction budget exhausted")
                return seconds

            def screenshot(name):
                owner.run(["import", "-display", env["DISPLAY"], "-window", "root", str(output / name)],
                          env, timeout=min(10, remaining()))

            time.sleep(min(args.startup_wait, remaining()))
            screenshot("before.png")
            receipt["terminal_processes"] = {str(pid): {"start_ticks": fields[2],
                "command": Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")}
                for pid, fields in terminal.members().items() if Path(f"/proc/{pid}/cmdline").exists()}
            if args.actions:
                script = args.actions.read_text()
                (output / "actions.xdo").write_text(script)
                receipt["driver_started_seconds"] = time.monotonic() - started
                # '-' is xdotool's native stdin script mode; no shell evaluation.
                with (output / "actions.xdo").open() as source:
                    owner.run(["xdotool", "-"], env, stdin=source,
                              stdout=stack.enter_context((output / "driver.log").open("w")),
                              stderr=subprocess.STDOUT,
                              timeout=max(.1, remaining() - args.tail_seconds - 1))
                receipt["driver_finished_seconds"] = time.monotonic() - started
                time.sleep(min(args.tail_seconds, remaining()))
            else:
                time.sleep(max(0, remaining() - 1))
            if terminal.process.poll() is not None:
                raise RuntimeError(f"Installed terminal exited during recording: {terminal.process.returncode}")
            screenshot("after.png")
            receipt["duration_seconds"] = time.monotonic() - started
            capture.stop(signal.SIGINT)
            receipt["capture_returncode"] = capture.process.returncode
            if capture.process.returncode not in (0, 255):
                raise RuntimeError(f"Video recorder exited {capture.process.returncode}")
            receipt["capture_completed"] = True
            receipt["runtime_after"] = selection.receipt(owner, env)
            receipt["runtime_unchanged"] = receipt["runtime_before"] == receipt["runtime_after"]
            # Quit through the installed application; then reap all owned descendants.
            terminal.members()
            owner.run(["xdotool", "key", "--window", window, "ctrl+q"], env, timeout=2)
            try:
                terminal.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            terminal.stop()
            xvfb.stop()
            info = owner.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                              str(output / "terminal.mp4")], env, stdout=subprocess.PIPE, text=True)
            receipt["video"] = json.loads(info.stdout)
            duration = float(receipt["video"]["format"]["duration"])
            if args.review_start >= duration:
                raise ValueError(f"Review start {args.review_start}s is outside the {duration}s recording")
            events_path = output / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
            receipt["events"] = events
            intervals = [(None, args.review_start, min(args.review_seconds, duration - args.review_start))]
            for label in args.review_phase:
                index = next((i for i, event in enumerate(events) if event["label"] == label), None)
                if index is None:
                    raise ValueError(f"Missing native script marker: {label}")
                start = events[index]["seconds_since_capture_launch"]
                end = events[index + 1]["seconds_since_capture_launch"] if index + 1 < len(events) else duration
                seconds = min(args.review_seconds, end - start, duration - start)
                if seconds <= 0:
                    raise ValueError(f"Marker {label} lies outside the video")
                intervals.append((label, start, seconds))
            receipt["review_intervals"] = [{"label": label or "main", "start": start, "seconds": seconds}
                                           for label, start, seconds in intervals]
            names = ["terminal.mp4", "before.png", "after.png"]
            for label, start, seconds in intervals:
                print(f"Preparing review {label or 'main'} at {start:.3f}s for {seconds:.3f}s", flush=True)
                artifacts(output, args, env, owner, start=start, seconds=seconds, label=label)
                names.extend([f"{label}-slow.mp4", f"{label}-frames.png"] if label else ["slow.mp4", "frames.png"])
            receipt["artifacts"] = {name: {"bytes": (output / name).stat().st_size,
                                         "sha256": digest(output / name)} for name in names}
            if any(item["bytes"] == 0 for item in receipt["artifacts"].values()):
                raise RuntimeError("Empty recording artifact")
            receipt["completed"] = True
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if capture is not None:
            try:
                capture.stop(signal.SIGINT)
            except (OSError, subprocess.SubprocessError) as error:
                receipt["capture_cleanup_error"] = str(error)
        receipt["cleanup"] = owner.cleanup()
        if receipt["cleanup"]["remaining_owned_pids"] or receipt["cleanup"]["errors"]:
            receipt["completed"] = False
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if not receipt["completed"]:
        raise RuntimeError("Recorder cleanup incomplete; inspect receipt.json")
    return output


def mark(label):
    """A native xdotool exec marker; timestamps bracket actual input injection."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", label):
        raise ValueError("Invalid phase label")
    output = Path(os.environ["TOAD_VIDEO_OUTPUT"]).resolve()
    if not output.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()) or not output.is_dir():
        raise ValueError("Marker needs the recorder's persistent scratch directory")
    display = os.environ["DISPLAY"]
    if not re.fullmatch(r":[1-9][0-9]*", display):
        raise ValueError("Marker needs an isolated display")
    event = {"label": label, "utc": datetime.now(timezone.utc).isoformat(),
             "seconds_since_capture_launch": time.monotonic() - float(os.environ["TOAD_VIDEO_EPOCH"])}
    if os.environ.get("TOAD_VIDEO_MARK_SNAPSHOTS") == "1":
        owner = ProcessOwner()
        try:
            name = f"phase-{label}.png"
            owner.run(["import", "-display", display, "-window", "root", str(output / name)],
                      os.environ.copy(), timeout=5)
            event["screenshot"] = name
        finally:
            owner.cleanup()
    with (output / "events.jsonl").open("a") as target:
        target.write(json.dumps(event) + "\n")
    print(json.dumps(event), flush=True)


def scroll_script():
    # Literal quoted paths avoid native xdotool stdin variable-expansion defects.
    marker = f"exec --sync {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} --mark "
    return "\n".join([
        "mousemove --sync 700 260", "click 1", marker + "focused", "sleep 1",
        marker + "up", "keydown Prior", "sleep 4", "keyup Prior", marker + "up-done",
        marker + "down", "keydown Next", "sleep 4", "keyup Next", marker + "down-done",
        marker + "reverse", "keydown Prior", "sleep 4", "keyup Prior", marker + "reverse-done",
        marker + "end", "key End", "sleep 1", marker + "idle", "sleep 4", marker + "idle-done", "",
    ])


def main():
    if sys.argv[1:] == ["--runtime-probe"]:
        print(json.dumps(runtime_probe()))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--mark":
        mark(sys.argv[2])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    parser.add_argument("--output", type=Path, default=Path.home() / ".cache/agent-scratch/toad-video" / stamp)
    parser.add_argument("--owner", default="installed-tui-video-tools", help="Owner retaining/cleaning this evidence")
    parser.add_argument("--actions", type=Path, help="Native xdotool stdin script with real clicks/keys/sleeps")
    parser.add_argument("--write-scroll-script", type=Path, help="Write an editable native held-key script, then exit")
    parser.add_argument("--review-phase", action="append", default=[], help="Also review this native script marker (up to 8)")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--fit-window", action="store_true")
    parser.add_argument("--startup-wait", type=float, default=8)
    parser.add_argument("--max-duration", type=float, default=45)
    parser.add_argument("--tail-seconds", type=float, default=2)
    parser.add_argument("--slowdown", type=float, default=8)
    parser.add_argument("--review-start", type=float, default=0)
    parser.add_argument("--review-seconds", type=float, default=3)
    parser.add_argument("--review-fps", type=float, default=8)
    parser.add_argument("--review-frames", type=int, default=24)
    parser.add_argument("--sheet-columns", type=int, default=4)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.write_scroll_script:
        destination = args.write_scroll_script.expanduser().resolve()
        if not destination.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
            parser.error("Scroll script must be under persistent agent scratch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x") as target:
            target.write(scroll_script())
        print(destination)
        return
    if len(args.review_phase) > 8 or len(set(args.review_phase)) != len(args.review_phase):
        parser.error("Use at most 8 distinct review phases")
    if any(not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", label) for label in args.review_phase):
        parser.error("Review phase must be a lowercase marker label")
    def interrupted(signum, frame):
        raise InterruptedError(f"Recorder interrupted by signal {signum}")
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    bounds = {"fps": (1, 120), "width": (320, 1920), "height": (240, 1200),
              "max_duration": (1, 120), "slowdown": (1, 16), "review_seconds": (.01, 15),
              "review_fps": (.1, 60), "review_frames": (1, 96), "sheet_columns": (1, 8),
              "startup_wait": (0, 119), "tail_seconds": (0, 119), "review_start": (0, 119)}
    for name, (low, high) in bounds.items():
        value = getattr(args, name)
        if not math.isfinite(value) or not low <= value <= high:
            parser.error(f"{name} must be finite and between {low} and {high}")
    if args.width % 2 or args.height % 2:
        parser.error("Capture dimensions must be even for yuv420p")
    if args.startup_wait + args.tail_seconds + 1 >= args.max_duration:
        parser.error("Duration must leave time for interaction and a final screenshot")
    if args.review_start >= args.max_duration or args.review_fps > args.fps:
        parser.error("Review must start within capture and sample no faster than capture FPS")
    frames = min(args.review_frames, max(1, math.ceil(args.review_seconds * args.review_fps)))
    pixels = 640 * args.sheet_columns * (640 * args.height / args.width) * math.ceil(frames / args.sheet_columns)
    if pixels > 24_000_000:
        parser.error("Contact sheet exceeds 24 million pixels; reduce review frames")
    print(record(args))


if __name__ == "__main__":
    main()
