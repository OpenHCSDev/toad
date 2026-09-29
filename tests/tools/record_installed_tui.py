#!/usr/bin/env python3
"""Record real installed terminal output without touching the desktop display."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import time


def stop(process: subprocess.Popen, *, sig=signal.SIGTERM) -> None:
    if process.poll() is None:
        process.send_signal(sig)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run(argv, env, *, stdout=subprocess.DEVNULL, timeout=30, **kwargs):
    return subprocess.run(argv, env=env, stdout=stdout, check=True, timeout=timeout, **kwargs)


def artifacts(output: Path, args, env) -> None:
    video = output / "terminal.mp4"
    common = ["ffmpeg", "-nostdin", "-y", "-loglevel", "warning"]
    interval = ["-ss", str(args.review_start), "-t", str(args.review_seconds), "-i", str(video)]
    run(common + interval + [
        "-vf", f"setpts={args.slowdown}*PTS", "-r", str(args.fps),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-threads", "1",
        str(output / "slow.mp4"),
    ], env, timeout=60)
    frames = min(args.review_frames, max(1, int(args.review_seconds * args.review_fps)))
    rows = (frames + args.sheet_columns - 1) // args.sheet_columns
    stamp = r"drawtext=text='%{pts\:hms}':fontsize=14:fontcolor=white:box=1:boxcolor=black:x=4:y=4"
    filters = f"fps={args.review_fps},{stamp},scale=640:-1,tile={args.sheet_columns}x{rows}:nb_frames={frames}"
    run(common + interval + ["-vf", filters, "-frames:v", "1", "-update", "1", str(output / "frames.png")], env)


def record(args) -> Path:
    output = args.output.expanduser().absolute()
    # Recordings can contain durable user history. Keep them on persistent storage.
    if any(output.is_relative_to(Path(path)) for path in ("/tmp", "/dev/shm", "/run")):
        raise ValueError("Recording output must be on persistent storage")
    output.mkdir(parents=True, exist_ok=False)
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        command = ["toad-comms"]
    required = ("Xvfb", "st", "xdotool", "ffmpeg", "import", command[0])
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"Missing programs: {', '.join(missing)}")
    env = os.environ.copy()
    env.pop("NO_COLOR", None)  # Codex tool shells can inherit NO_COLOR=1.
    receipt = {
        "command": command, "terminal_command": ["st", "-e", *command],
        "fps": args.fps, "screen": [args.width, args.height],
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "assessment": "unreviewed", "completed": False,
    }
    runtime = Path(os.path.realpath(shutil.which("agent-comms-acp") or "/nonexistent")).parent.parent
    activation = runtime / "activation.json"
    if activation.is_file():
        receipt["runtime_activation"] = json.loads(activation.read_text())
    processes = []
    capture = terminal = driver = None
    try:
        read_fd, write_fd = os.pipe()
        try:
            xvfb = subprocess.Popen([
                "Xvfb", "-displayfd", str(write_fd), "-screen", "0",
                f"{args.width}x{args.height}x24", "-nolisten", "tcp",
            ], pass_fds=(write_fd,), stderr=(output / "xvfb.log").open("w"))
            processes.append(xvfb)
        finally:
            os.close(write_fd)
        with os.fdopen(read_fd) as pipe:
            if not select.select([pipe], [], [], 10)[0]:
                raise TimeoutError("Virtual display did not start")
            number = pipe.readline().strip()
        if not number.isdecimal():
            raise RuntimeError("Virtual display returned no display number")
        env["DISPLAY"] = ":" + number
        receipt["display"] = env["DISPLAY"]
        terminal = subprocess.Popen(["st", "-e", *command], env=env,
                                    stderr=(output / "terminal.log").open("w"))
        processes.append(terminal)
        window = run(["xdotool", "search", "--sync", "--pid", str(terminal.pid)], env,
                     stdout=subprocess.PIPE, timeout=10, text=True).stdout.splitlines()[0]
        run(["xdotool", "windowfocus", "--sync", window], env)
        if args.fit_window:
            run(["xdotool", "windowsize", window, str(args.width - 20), str(args.height - 20)], env)
        receipt["window"] = window
        capture = subprocess.Popen([
            "ffmpeg", "-nostdin", "-y", "-loglevel", "warning", "-f", "x11grab",
            "-framerate", str(args.fps), "-video_size", f"{args.width}x{args.height}",
            "-i", env["DISPLAY"], "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "26", "-threads", "1", "-pix_fmt", "yuv420p", str(output / "terminal.mp4"),
        ], stderr=(output / "capture.log").open("w"))
        started = time.monotonic()
        deadline = started + args.max_duration
        print(f"Recording isolated display {env['DISPLAY']}: {output}", flush=True)
        time.sleep(args.startup_wait)
        run(["import", "-display", env["DISPLAY"], "-window", "root", str(output / "before.png")], env)
        if args.actions:
            script = args.actions.read_text()
            (output / "actions.xdo").write_text(script)
            receipt["driver_started_seconds"] = time.monotonic() - started
            with (output / "actions.xdo").open() as source:
                driver = subprocess.Popen(["xdotool", "-"], stdin=source, env=env,
                                          stdout=(output / "driver.log").open("w"),
                                          stderr=subprocess.STDOUT)
                processes.append(driver)
                driver.wait(timeout=max(.1, deadline - time.monotonic() - args.tail_seconds))
            if driver.returncode != 0:
                raise RuntimeError(f"Click driver exited {driver.returncode}")
            receipt["driver_finished_seconds"] = time.monotonic() - started
            time.sleep(args.tail_seconds)
        else:
            time.sleep(max(0, deadline - time.monotonic()))
        if terminal.poll() is not None:
            raise RuntimeError(f"Installed terminal exited during recording: {terminal.returncode}")
        run(["import", "-display", env["DISPLAY"], "-window", "root", str(output / "after.png")], env)
        receipt["duration_seconds"] = time.monotonic() - started
        stop(capture, sig=signal.SIGINT)
        if capture.returncode != 0:
            raise RuntimeError(f"Video recorder exited {capture.returncode}")
        receipt["completed"] = True
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if capture is not None:
            stop(capture, sig=signal.SIGINT)
        if driver is not None:
            stop(driver)
        if terminal is not None and terminal.poll() is None:
            try:
                run(["xdotool", "key", "--window", window, "ctrl+q"], env, timeout=2)
                terminal.wait(timeout=5)
            except (subprocess.SubprocessError, UnboundLocalError):
                stop(terminal)
        for process in reversed(processes):
            stop(process)
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    artifacts(output, args, env)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    parser.add_argument("--output", type=Path, default=Path.home() / ".cache/agent-scratch/toad-video" / stamp)
    parser.add_argument("--actions", type=Path, help="Native xdotool script with real clicks/keys/sleeps")
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
    for name in ("fps", "width", "height", "max_duration", "slowdown", "review_seconds", "review_fps", "review_frames", "sheet_columns"):
        if getattr(args, name) <= 0:
            parser.error(f"{name} must be positive")
    if args.startup_wait < 0 or args.tail_seconds < 0 or args.review_start < 0:
        parser.error("Timing offsets must be nonnegative")
    if args.startup_wait + args.tail_seconds >= args.max_duration:
        parser.error("Duration must leave time for the actual interaction")
    print(record(args))


if __name__ == "__main__":
    main()
