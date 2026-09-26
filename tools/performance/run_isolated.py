"""Run a bounded real-terminal workload on an owned Xvfb display, with cleanup."""

import argparse
from hashlib import sha256
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import time

import psutil

TOOLS = Path(__file__).resolve().parent
REPOSITORY = TOOLS.parents[1]


def source_hashes(root):
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root,
    ).decode().split("\0")
    return {path: sha256((root / path).read_bytes()).hexdigest() for path in sorted(set(paths))
            if Path(path).suffix in {".py", ".tcss", ".toml"} and (root / path).is_file()}

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=REPOSITORY)
parser.add_argument("--framework", type=Path, required=True)
parser.add_argument("--environment", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, default=Path.home() / ".cache/toad-performance")
parser.add_argument("--dependency-path", type=Path, action="append", default=[])
parser.add_argument("--launcher", type=Path, help="Explicit launcher required for non-fixture workloads")
parser.add_argument("--name", required=True)
parser.add_argument("--display", default=":96")
parser.add_argument("--profile", action="store_true")
parser.add_argument("--profile-gil", action="store_true")
parser.add_argument("--profile-seconds", type=int, default=180)
parser.add_argument("--py-spy", default="py-spy")
parser.add_argument("--profile-sudo", action="store_true")
parser.add_argument("--navigation-only", action="store_true")
parser.add_argument("--open-only", action="store_true")
parser.add_argument("--wire-views", action="store_true")
parser.add_argument("--census", action="store_true")
parser.add_argument("--privileged-display", action="store_true")
parser.add_argument("--fixture", action="store_true")
parser.add_argument("--sidebar-only", action="store_true")
parser.add_argument("--sidebar-cycles", type=int, default=4)
parser.add_argument("--resize-only", action="store_true")
parser.add_argument("--resize-sidebars", action="store_true")
parser.add_argument("--filters-only", action="store_true")
parser.add_argument("--tabs", type=int, default=10)
parser.add_argument("--focused-profile", choices=("memray", "cprofile"))
args = parser.parse_args()
assert Path(args.name).name == args.name, "Name must be a capture basename"
args.source, args.framework, args.environment = (path.expanduser().resolve() for path in (args.source, args.framework, args.environment))
args.output_dir = args.output_dir.expanduser().resolve()
args.output_dir.mkdir(parents=True, exist_ok=True)
base = args.output_dir / args.name
assert not Path(str(base) + "-manifest.json").exists(), "Choose a fresh capture name"
launcher = str(TOOLS / "launch_fixture.sh") if args.fixture else str(args.launcher.resolve()) if args.launcher else None
assert launcher is not None, "Non-fixture runs require --launcher"
site_packages = subprocess.check_output([str(args.environment / "bin/python"), "-c",
    "import os,site; print(os.pathsep.join(site.getsitepackages()))"], text=True).strip()
extra_paths = [str(path.expanduser().resolve()) for path in args.dependency_path]
if os.environ.get("TOAD_VALIDATION_EXTRA_PYTHONPATH"):
    extra_paths.append(os.environ["TOAD_VALIDATION_EXTRA_PYTHONPATH"])
env = dict(os.environ, DISPLAY=args.display, TOAD_TEST_SOURCE=str(args.source), TOAD_TEST_FRAMEWORK=str(args.framework),
           TOAD_TEST_ENVIRONMENT=str(args.environment),
           TOAD_TEST_SITE_PACKAGES=site_packages, TOAD_PERF_TOOLS_DIR=str(TOOLS),
           TOAD_ARTIFACT_ROOT=str(args.output_dir), TOAD_VALIDATION_EXTRA_PYTHONPATH=os.pathsep.join(extra_paths),
           TOAD_VALIDATION_TRACE=str(base) + "-trace.json",
            TOAD_VALIDATION_SNAPSHOT=str(base) + "-state.json")
if args.fixture:
    env["TOAD_FIXTURE_READY"] = str(base) + "-fixture-ready.json"
if args.filters_only:
    assert args.fixture, "Filter-input stress uses only the isolated fixed fixture"
    env["TOAD_FIXTURE_ALL_CATEGORIES"] = "1"
    env["TOAD_VALIDATION_FILTER_PROBE"] = "1"
if args.census:
    env["TOAD_VALIDATION_CENSUS"] = str(base) + "-census.jsonl"
if args.focused_profile:
    env["TOAD_VALIDATION_FOCUSED_PROFILE"] = args.focused_profile
    env["TOAD_VALIDATION_PROFILE_BASE"] = str(base)
server_log_path = Path(str(base) + "-xvfb.log")
display_number = args.display.removeprefix(":").split(".")[0]
assert not Path(f"/tmp/.X11-unix/X{display_number}").exists(), "Display already has an endpoint"
assert not Path(f"/tmp/.X{display_number}-lock").exists(), "Display already has a lock"
with server_log_path.open("wb") as server_log:
    server = subprocess.Popen([*(["sudo", "-n"] if args.privileged_display else []),
                              "Xvfb", args.display, "-screen", "0", "3840x2160x24", "-nolisten", "tcp"],
                              stdout=server_log, stderr=server_log)
terminal = None
window = pid = None
try:
    until = time.monotonic() + 10
    while time.monotonic() < until:
        assert server.poll() is None, f"Xvfb failed to start: {server_log_path.read_text()}"
        probe = subprocess.run(["xdotool", "getdisplaygeometry"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            break
        time.sleep(.1)
    else:
        raise TimeoutError(f"Xvfb endpoint did not become ready: {server_log_path.read_text()}")
    with Path(str(base) + "-terminal.log").open("wb") as terminal_log:
        terminal = subprocess.Popen(["st", "-t", "Toad isolated work comparison", "-g", "307x81", "-e", "bash", launcher],
                                    env=env, stdout=terminal_log, stderr=terminal_log)
    until = time.monotonic() + 30
    while time.monotonic() < until:
        assert terminal.poll() is None, "Test terminal exited before startup"
        found = subprocess.run(["xdotool", "search", "--pid", str(terminal.pid)], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        children = psutil.Process(terminal.pid).children()
        if found.returncode == 0 and children:
            child = children[0]
            fixture_ready = False
            if args.fixture:
                try:
                    receipt = json.loads(Path(env["TOAD_FIXTURE_READY"]).read_text())
                    fixture_ready = receipt["pid"] == child.pid and receipt["driver"] == "sidebar_validation_driver:ValidationDriver"
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
            if child.cmdline()[0] == "toad" and (fixture_ready if args.fixture else any(
                    "agent_comms.acp" in p.cmdline() for p in child.children(recursive=True))):
                window, pid = int(found.stdout.splitlines()[0]), child.pid
                break
        time.sleep(.2)
    assert window is not None and pid is not None, "Observer UI did not initialize"
    time.sleep(3)
    if args.census:
        os.kill(pid, signal.SIGUSR2)
        time.sleep(1)
    subprocess.run(["xdotool", "windowfocus", str(window), "mousemove", "--window", str(window), "625", "680"],
                   env=env, check=True)
    manifest = {"source": str(args.source), "head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.source, text=True).strip(),
        "status": subprocess.check_output(["git", "status", "--short"], cwd=args.source, text=True),
        "environment": str(args.environment), "framework": str(args.framework), "framework_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=args.framework, text=True).strip(),
        "framework_status": subprocess.check_output(["git", "status", "--short"], cwd=args.framework, text=True),
        "display": args.display, "pid": pid, "window": window,
        "source_hashes": source_hashes(args.source), "framework_hashes": source_hashes(args.framework),
        "legacy_markdown_measurement": env.get("TOAD_VALIDATION_LEGACY_MARKDOWN_MEASUREMENT") == "1",
        "focused_profile": args.focused_profile, "layout_causes": env.get("TOAD_VALIDATION_LAYOUT_CAUSES") == "1",
        "ungated_startup": env.get("TOAD_VALIDATION_UNGATED_STARTUP") == "1",
        "open_stages": env.get("TOAD_VALIDATION_OPEN_STAGES") == "1",
        "observer_sha256": sha256((TOOLS / "sidebar_validation_driver.py").read_bytes()).hexdigest(),
        "dependency_paths": extra_paths}
    Path(str(base) + "-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    profile_args = (["--profile", str(base) + ".speedscope.json", "--profile-seconds", str(args.profile_seconds)] if args.profile else [])
    if args.profile_gil:
        profile_args.append("--profile-gil")
    if args.profile:
        profile_args.extend(("--py-spy", args.py_spy))
        if args.profile_sudo:
            profile_args.append("--profile-sudo")
    if args.navigation_only:
        profile_args.append("--navigation-only")
    if args.open_only:
        profile_args.append("--open-only")
    if args.wire_views:
        profile_args.append("--wire-views")
    if args.fixture:
        profile_args.extend(("--fixture-ready", env["TOAD_FIXTURE_READY"]))
    if args.sidebar_only:
        profile_args.extend(("--sidebar-only", "--sidebar-cycles", str(args.sidebar_cycles)))
    if args.resize_only:
        profile_args.append("--resize-only")
    if args.resize_sidebars:
        profile_args.append("--resize-sidebars")
    if args.filters_only:
        profile_args.append("--filters-only")
    if args.focused_profile:
        profile_args.extend(("--profile-state", str(base) + "-profile-state.json"))
    result = subprocess.run([
        sys.executable, str(TOOLS / "terminal_stress.py"), "--window", str(window), "--pid", str(pid),
        "--output", str(base) + "-actions.json", "--snapshot", str(base) + "-state.json", "--tabs", str(args.tabs),
        "--duration", "240", "--base-mode", "session-1", "--launcher", launcher, *profile_args,
    ], env=env, timeout=245)
    if psutil.pid_exists(pid) and terminal.poll() is None:
        if args.census:
            os.kill(pid, signal.SIGUSR2)
            time.sleep(1)
        subprocess.run(["import", "-window", str(window), str(base) + "-final.png"], env=env, check=True)
    else:
        print({"ui_exited_before_final_capture": True, "terminal_returncode": terminal.poll()})
    raise SystemExit(result.returncode)
finally:
    try:
        if window is not None and terminal is not None and terminal.poll() is None:
            subprocess.run(["xdotool", "key", "--window", str(window), "ctrl+q"], env=env, check=False)
            terminal.wait(timeout=90)
    finally:
        if args.privileged_display and server.poll() is None:
            owned = psutil.Process(server.pid)
            processes = [owned, *owned.children(recursive=True)]
            for process in processes:
                command = process.cmdline()
                if command and Path(command[0]).name == "Xvfb" and args.display in command:
                    subprocess.run(["sudo", "-n", "kill", "-TERM", str(process.pid)], check=True)
        elif server.poll() is None:
            server.terminate()
        server.wait(timeout=5)
