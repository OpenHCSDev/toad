#!/usr/bin/env python3
"""Record real installed terminal output without touching the desktop display."""
from __future__ import annotations

import argparse
from abc import abstractmethod
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict
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
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily


class ProfileSampling(DeclaredFamily, affix="Sampling"):
    """The profiler owns consistency; capture must record its actual policy."""

    arguments = ()
    limitation = "Consistent sampling briefly pauses Python; compare an unprofiled journey for observer overhead"


class ConsistentSampling(ProfileSampling):
    pass


class NonblockingSampling(ProfileSampling):
    arguments = ("--nonblocking",)
    limitation = "Nonblocking reads can observe inconsistent Python stacks; inspect sampling errors before attribution"


class ThreadSampling(DeclaredFamily, affix="ThreadSampling"):
    """Declare which sampled threads answer the intended profiling question."""

    arguments = ()
    limitation = "Default thread selection measures sampled wall stacks; parallel waiting spans are not process CPU attribution"


class AllThreadSampling(ThreadSampling):
    pass


class GilThreadSampling(ThreadSampling):
    arguments = ("--gil",)
    limitation = "GIL-owner samples cover Python execution; released-GIL/native work is omitted, so corroborate with kernel CPU counters"


class ReviewTiming(DeclaredFamily, affix="ReviewTiming"):
    """Clip encoding is an independent resource lifetime, never native work."""

    @classmethod
    @abstractmethod
    def generate(cls, output, args, env, owner, intervals): ...


class InlineReviewTiming(ReviewTiming):
    @classmethod
    def generate(cls, output, args, env, owner, intervals):
        names = []
        for interval in intervals:
            label = interval["label"]
            label = None if label == "main" else label
            print(f"Preparing review {label or 'main'} at {interval['start']:.3f}s for {interval['seconds']:.3f}s", flush=True)
            artifacts(output, args, env, owner, start=interval["start"], seconds=interval["seconds"], label=label)
            names.extend([f"{label}-slow.mp4", f"{label}-frames.png"] if label else ["slow.mp4", "frames.png"])
        return names


class DeferredReviewTiming(ReviewTiming):
    @classmethod
    def generate(cls, output, args, env, owner, intervals):
        return []

if TYPE_CHECKING:
    from agent_comms.child_process import ParentedProcess, ObservedProcess, ProcessIdentity
    from agent_comms.active_route import ActiveRoute
    from agent_comms.registration import Registration


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
    child: ParentedProcess | ObservedProcess
    registration: Registration | None = None

    @property
    def process(self):
        return self.child.process

    def members(self):
        # Group custody comes from the installed platform authority. Detached
        # application owners are never adopted merely because they are children.
        members = self.child.platform.group_members(self.child.identity)
        if self.registration is None:
            return members
        owners = {thread.process_identity for thread in
                  self.registration.snapshot().threads.values()
                  if thread.process_identity is not None}
        return tuple(identity for identity in members if identity not in owners)

    def send_signal(self, sig):
        for identity in self.members():
            try:
                self.child.platform.send(identity, sig)
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
        return [identity.pid for identity in self.members()]

    def receipt(self):
        return {"pid": self.child.identity.pid, "start_ticks": self.child.identity.start_time,
                "returncode": self.process.returncode}


class TransferredGroup(OwnedProcess):
    """Custody of one verified launch identity through installed ObservedProcess."""

    def stop(self, sig=signal.SIGTERM):
        self.send_signal(sig)
        deadline = time.monotonic() + 3
        while self.members() and time.monotonic() < deadline:
            time.sleep(.05)
        if self.members():
            self.send_signal(signal.SIGKILL)
        deadline = time.monotonic() + 2
        while self.members() and time.monotonic() < deadline:
            time.sleep(.05)
        return [identity.pid for identity in self.members()]

    def receipt(self):
        return {"pid": self.child.identity.pid, "start_ticks": self.child.identity.start_time,
                "custody": "verified launch identity transferred to installed ObservedProcess"}


class ProcessOwner:
    """One launcher/timeout/cleanup mechanism for all recorder subprocesses."""

    def __init__(self, registration: Registration | None = None):
        self.children = []
        self.registration = registration

    def start(self, argv, *, before_start=None, **kwargs):
        from agent_comms.child_process import Platform
        text = kwargs.pop("text", False)
        with Platform.current().launch(tuple(argv), tuple(kwargs.pop("pass_fds", ()))) as launch:
            child = launch.spawn(**kwargs)
            try:
                if before_start is not None:
                    before_start(child.identity)
                launch.release(child.identity)
                launch.verify()
            except BaseException:
                launch.cancel_before_release(child.identity)
                child.reap()
                child.close_streams()
                raise
        # Popen communicates bytes; text conversion belongs to this boundary.
        owned = OwnedProcess(child, self.registration)
        owned.text = text
        self.children.append(owned)
        return owned

    def transfer(self, pid, start_ticks):
        from agent_comms.child_process import ObservedProcess, ProcessIdentity
        owned = TransferredGroup(ObservedProcess(ProcessIdentity(pid, start_ticks)), self.registration)
        self.children.append(owned)
        return owned

    def run(self, argv, env, *, timeout=30, stdout=subprocess.DEVNULL, **kwargs):
        owned = self.start(argv, env=env, stdout=stdout, **kwargs)
        try:
            out, err = owned.process.communicate(timeout=timeout)
            if owned.text:
                out = out.decode() if out is not None else None
                err = err.decode() if err is not None else None
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
                "custody": "installed ParentedProcess and Platform process groups; no descendant adoption",
                "processes": [o.receipt() for o in self.children]}



def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_probe():
    """Executed by the selected runtime interpreter, without loading the app."""
    result = {"python": sys.executable, "prefix": sys.prefix, "packages": {}}
    if target := os.environ.get("TOAD_VIDEO_CAPTURE_TARGET"):
        route = CaptureTarget.decode(target).read_route(os.environ)
        root = route.observe_root()
        result["route"] = {"root": str(root), "wire_root_id": route.wire_root_id,
                           "native_package": str(route.native_package.resolve())}
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
        runtime = env.get("AGENT_COMMS_RUNTIME_ROOT")
        if runtime:
            return cls(launcher, Path(runtime).expanduser().absolute(), "AGENT_COMMS_RUNTIME_ROOT")
        acp = env.get("AGENT_COMMS_ACP_LAUNCHER") or shutil.which("agent-comms-acp")
        acp = acp or str(Path.home() / ".local/bin/agent-comms-acp")
        return cls(launcher, Path(acp).resolve().parent,
                   "AGENT_COMMS_ACP_LAUNCHER" if env.get("AGENT_COMMS_ACP_LAUNCHER") else "PATH agent-comms-acp")

    def apply_environment(self, env):
        # An explicit candidate is pinned. Default-entrypoint acceptance must
        # follow the installed launcher itself, without injecting an override.
        if env.get("AGENT_COMMS_RUNTIME_ROOT"):
            env["AGENT_COMMS_RUNTIME_ROOT"] = str(self.bin_directory.resolve())

    def receipt(self, owner, env, command):
        observed = self.from_environment(command, env)
        if (observed.launcher != self.launcher
                or observed.bin_directory.resolve() != self.bin_directory.resolve()):
            raise ValueError("Installed launcher selection changed during capture")
        result = {"selection": self.selection, "bin_directory": str(self.bin_directory.resolve()),
                  "launcher": str(self.launcher), "launcher_sha256": digest(self.launcher)}
        paths = {
            "command": shutil.which(command[0]) or command[0],
            "acp": env.get("AGENT_COMMS_ACP_LAUNCHER") or shutil.which("agent-comms-acp")
                   or str(Path.home() / ".local/bin/agent-comms-acp"),
        }
        result["launcher_links"] = {name: {"selected_path": str(Path(path).absolute()),
                                          "resolved_path": str(Path(path).resolve()),
                                          "sha256": digest(Path(path))}
                                    for name, path in paths.items()}
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
        route = result["observed"].get("route")
        if route is not None:
            native = result.get("activation", {}).get("native_package")
            if not native or Path(native).resolve() != Path(route["native_package"]):
                raise ValueError("Candidate activation and private route native packages must match")
        return result


class PhysicalJourney(DeclaredFamily, affix="Journey"):
    """Declare the bounded, input-free physical journeys permitted on a live owner."""

    @classmethod
    @abstractmethod
    def script(cls, args): ...


class ScrollJourney(PhysicalJourney):
    @classmethod
    def script(cls, args):
        return scroll_script(idle_seconds=args.scroll_idle_seconds)


class SavedTabCloseJourney(PhysicalJourney):
    @classmethod
    def script(cls, args):
        marker = marker_command()
        settle = f"sleep {args.navigation_settle_seconds:g}"
        return "\n".join([
            marker + "open-existing", f"mousemove --sync {args.other_agent_x} {args.other_agent_y}",
            "click 1", settle, marker + "existing-opened",
            f"mousemove --sync {args.return_tab_x} {args.close_tab_y}", "click 1", settle,
            marker + "close", f"mousemove --sync {args.close_tab_x} {args.close_tab_y}",
            "click 1", settle, marker + "close-done",
            marker + "reopen", f"mousemove --sync {args.reopen_agent_x} {args.reopen_agent_y}",
            "click 1", settle, marker + "reopened", "",
        ])


class CaptureTarget(DeclaredFamily, affix="Capture"):
    """Own launch authorization and original native-owner preservation proof."""

    @classmethod
    @abstractmethod
    def admit(cls, args, command, env): ...

    @classmethod
    @abstractmethod
    def read_route(cls, env): ...

    @abstractmethod
    def observe(self): ...


@dataclass(frozen=True)
class PrivateCapture(CaptureTarget):
    root: Path
    selection: RuntimeSelection

    @classmethod
    def read_route(cls, env):
        from agent_comms.active_route import ActiveRoute
        return ActiveRoute(Path(env["AGENT_COMMS_ROOT"]), env["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"],
                           Path(env["AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE"]))

    @classmethod
    def admit(cls, args, command, env):
        from agent_comms.active_route import read_active_route
        if args.private_root is None:
            raise ValueError("Private capture requires an existing matched --private-root")
        root = args.private_root.expanduser().resolve()
        if not root.is_dir() or root == (Path.home() / ".agent-comms").resolve():
            raise ValueError("Private fixture root must already exist")
        if Path(env.get("AGENT_COMMS_ROOT", "")).resolve() != root:
            raise ValueError("Private fixture root must match explicit AGENT_COMMS_ROOT")
        active = read_active_route()
        if active is not None and root == active.root.resolve():
            raise ValueError("Private capture refuses the owner's active bus")
        if Path(command[0]).name != "toad":
            raise ValueError("Private capture requires installed toad acp; toad-comms clears private pins")
        selection = RuntimeSelection.from_environment(command, env)
        expected_acp = shlex.join([str(selection.bin_directory / "python"), "-m", "agent_comms.acp"])
        if (len(command) < 4 or command[1:3] != ["acp", expected_acp]
                or Path(command[0]).resolve() != (selection.bin_directory / "toad").resolve()):
            raise ValueError("Private capture requires selected installed toad acp and its paired Python ACP command")
        return cls(root, selection)

    def observe(self):
        return {"root": str(self.root), "mode": self.declared_name}


@dataclass(frozen=True)
class ExistingThreadCapture(CaptureTarget):
    """Explicit authorized read-only attachment, never a fixture/native owner."""

    route: ActiveRoute
    name: str
    identity: ProcessIdentity
    selection: RuntimeSelection

    @property
    def root(self):
        return self.route.root

    @classmethod
    def read_route(cls, env):
        from agent_comms.active_route import read_active_route
        route = read_active_route()
        if route is None:
            raise ValueError("Existing-thread capture requires the installed active route")
        return route

    @classmethod
    def admit(cls, args, command, env):
        from agent_comms.registration import Registration
        if args.private_root is not None:
            raise ValueError("Existing-thread capture derives its root from the canonical active route")
        if len(command) != 2 or Path(command[0]).name != "toad-comms":
            raise ValueError("Existing-thread capture requires toad-comms and one explicit registered thread")
        if args.actions is not None and args.actions.read_text() != args.journey.script(args):
            raise ValueError("Existing-thread capture requires the selected canonical input-free physical journey")
        # Match the real default launcher's environment, not a copied private
        # route or thread identity that would redirect its retained history.
        for key in ("AGENT_COMMS_ROOT", "AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID", "AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE",
                    "AGENT_COMMS_THREAD", "AGENT_COMMS_MANAGED", "PI_AGENT_ID", "PI_PARENT_ID", "PI_TASK", "PI_WORKTREE", "PI_PROMPT"):
            env.pop(key, None)
        route = cls.read_route(env)
        route.observe_root()
        thread = Registration(route.root / "registry.json").require(command[1])
        identity = thread.process_identity
        if identity is None or not identity.alive():
            raise ValueError("Existing-thread capture requires an already running owner; it must not start one")
        return cls(route, thread.name, identity, RuntimeSelection.from_environment(command, env))

    def observe(self):
        from agent_comms.registration import Registration
        from agent_comms.field_codec import FieldCodec
        if self.read_route(os.environ) != self.route:
            raise ValueError("Existing-thread capture's canonical route changed")
        thread = Registration(self.root / "registry.json").require(self.name)
        if thread.process_identity != self.identity or not self.identity.alive():
            raise ValueError("Existing-thread capture's original native owner changed or exited")
        return {"root": str(self.root), "mode": self.declared_name, "name": self.name,
                "identity": FieldCodec.encode(self.identity), "original_owner_alive": True}


def cpu_snapshot(root_pid):
    """Read existing kernel counters for the launched terminal and its workers."""
    table = process_table()
    selected = {pid for pid, (_, sid, _, _) in table.items() if sid == root_pid}
    if root_pid in table:
        selected.add(root_pid)
    while True:
        children = {pid for pid, (parent, _, _, _) in table.items() if parent in selected}
        if children <= selected:
            break
        selected |= children
    result = {}
    for pid in selected:
        try:
            path = Path(f"/proc/{pid}")
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            result[str(pid)] = {"start_ticks": int(fields[19]),
                "cpu_seconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
                "command": (path / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")}
        except (OSError, ValueError, IndexError):
            continue
    return result


def terminal_program(owner, identity, deadline, before_ready=None):
    """Verify st's one launched program and its separate OS session identity."""
    from agent_comms.child_process import ProcessIdentity
    program = None
    while time.monotonic() < deadline and identity.alive():
        # st owns exactly one -e program. Read its direct launch relationship,
        # not a census of descendants that could include durable comms owners.
        child_ids = Path(f"/proc/{identity.pid}/task/{identity.pid}/children")
        try:
            children = [int(pid) for pid in child_ids.read_text().split()]
        except FileNotFoundError:
            break
        if len(children) > 1:
            raise RuntimeError("Terminal launch has ambiguous program custody")
        if children:
            try:
                if program is None and os.getsid(children[0]) == children[0]:
                    launched = ProcessIdentity.capture(children[0])
                    program = owner.transfer(launched.pid, launched.start_time)
                    if before_ready is not None:
                        before_ready(launched)
                # Verify the selected interpreter, rather than a command name.
                if program is not None and program.child.identity.alive() and (
                    Path(f"/proc/{program.child.identity.pid}/exe").resolve() == Path(sys.executable).resolve()
                ):
                    return program
            except ProcessLookupError:
                pass
        time.sleep(.05)
    raise RuntimeError("Installed terminal program did not acquire a verified runtime identity")


def publish_terminal_lease(output, identity):
    path = output / "profile-terminal.json"
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(identity) + "\n")
    pending.replace(path)


def profile_launch(command):
    """Launch plain st, then exec py-spy as an ancestor of the verified UI PID."""
    from agent_comms.registration import Registration
    output = Path(os.environ["TOAD_VIDEO_OUTPUT"])
    route = CaptureTarget.decode(os.environ["TOAD_VIDEO_CAPTURE_TARGET"]).read_route(os.environ)
    owner = ProcessOwner(Registration(route.root / "registry.json"))
    def interrupted(signum, frame):
        raise InterruptedError(f"Profiler launch interrupted by signal {signum}")
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    def transfer_terminal(identity):
        # Publish custody while Core's exec gate is closed, before st can run.
        publish_terminal_lease(output, {"pid": identity.pid, "start_ticks": identity.start_time})
    def transfer_program(identity):
        lease = json.loads((output / "profile-terminal.json").read_text())
        lease["program"] = {"pid": identity.pid, "start_ticks": identity.start_time}
        publish_terminal_lease(output, lease)
    try:
        terminal = owner.start(["st", "-e", *command], env=os.environ.copy(),
                               before_start=transfer_terminal)
        deadline = time.monotonic() + 10
        program = terminal_program(owner, terminal.child.identity, deadline, transfer_program)
        ui_pid = program.child.identity.pid
        # The real default wrapper first resolves its registered worktree in
        # a child Python process, then execs the UI in this same identity. A
        # profiler must attach after that exec, not to the temporary shell.
        expected_python = Path(sys.executable).resolve()
        while Path(f"/proc/{ui_pid}/exe").resolve() != expected_python:
            if not program.child.identity.alive() or time.monotonic() >= deadline:
                raise RuntimeError("Installed terminal did not exec the selected Python UI before profiling")
            time.sleep(.02)
        sampling = ProfileSampling.decode(os.environ["TOAD_VIDEO_PROFILE_SAMPLING"])
        threads = ThreadSampling.decode(os.environ["TOAD_VIDEO_PROFILE_THREADS"])
        argv = [shutil.which("py-spy"), "record", "--pid", str(ui_pid), "--format", "chrometrace",
                "--subprocesses", "--full-filenames", *sampling.arguments, *threads.arguments,
                "--rate", os.environ["TOAD_VIDEO_PROFILE_RATE"],
                "--duration", os.environ["TOAD_VIDEO_PROFILE_DURATION"],
                "--output", str(output / "cpu-profile.json")]
        (output / "profile-launch.json").write_text(json.dumps({
            "terminal_pid": terminal.process.pid, "terminal_start_ticks": terminal.child.identity.start_time,
            "ui_pid": ui_pid, "ui_start_ticks": program.child.identity.start_time, "profiler_command": argv,
            "sampling": sampling.declared_name,
            "threads": threads.declared_name,
            "profiler_exec_monotonic": time.monotonic()}) + "\n")
        # exec preserves the ancestor identity that Linux ptrace admission requires.
        os.execv(argv[0], argv)
    finally:
        owner.cleanup()


def profile_review(output, receipt, rate):
    """Decode py-spy's Chrome trace once and map samples to native action spans."""
    trace_path = output / "cpu-profile.json"
    if trace_path.stat().st_size > 128 * 1024 * 1024:
        raise RuntimeError("CPU profile exceeds the 128 MiB review bound")
    trace = json.loads(trace_path.read_text())
    stacks = defaultdict(list)
    spans = []
    for event in trace:
        identity = (event["pid"], event["tid"])
        if event["ph"] == "B":
            stacks[identity].append((event, []))
        elif event["ph"] == "E" and stacks[identity]:
            begin, children = stacks[identity].pop()
            cursor = begin["ts"]
            self_spans = []
            for child_start, child_end in children:
                if child_start > cursor:
                    self_spans.append((cursor, child_start))
                cursor = max(cursor, child_end)
            if event["ts"] > cursor:
                self_spans.append((cursor, event["ts"]))
            spans.append((begin, event["ts"], self_spans))
            if stacks[identity]:
                stacks[identity][-1][1].append((begin["ts"], event["ts"]))
    launch = json.loads((output / "profile-launch.json").read_text())
    if not any(begin["pid"] == launch["ui_pid"] and begin["args"]["filename"] for begin, _, _ in spans):
        raise RuntimeError("Profiler did not sample the actual installed UI PID")
    lower = launch["profiler_exec_monotonic"]
    upper = receipt["profiler"]["sampling_ready_observed_monotonic"]
    origin = (lower + upper) / 2
    offset = origin - receipt["capture_launch_monotonic"]
    sampling = ProfileSampling.decode(launch["sampling"])
    threads = ThreadSampling.decode(launch["threads"])
    result = {"profiler": "py-spy", "rate_hz": rate, "sampling": sampling.declared_name,
        "threads": threads.declared_name,
        "trace": "cpu-profile.json", "trace_origin_monotonic_estimate": origin,
        "trace_to_video_offset_seconds": offset,
        "ui_pid": launch["ui_pid"],
        "trace_origin_monotonic_bounds": [lower, upper],
        "alignment": "profiler exec to sampling-ready observation bound; approximate midpoint",
        "alignment_nominal_uncertainty_seconds": (upper - lower) / 2 + 1 / rate,
        "limits": ["Scheduler delays and sampling errors can increase clock uncertainty",
            sampling.limitation,
            threads.limitation,
                   "Stack spans are sampled wall activity, not exact call counts or CPU time",
                   "Kernel counter deltas give per-process CPU time at action boundaries",
                   "Sampled functions identify activation/preparation/layout/paint activity; no production event hook supplies exact phase timestamps",
                   "No automatic inference that a UI frame passed or a function is redundant"],
        "processes": sorted({str(event["pid"]) for event in trace}), "phases": []}
    log = (output / "profiler.log").read_text()
    quality = re.search(r"Samples: (\d+) Errors: (\d+)", log)
    if quality:
        result["sample_count"] = int(quality[1])
        result["sampling_errors"] = int(quality[2])
        result["sampling_quality"] = "partial; inspect errors and missing thread intervals" if int(quality[2]) else "no reported sampling errors"
    events = receipt["events"]
    for index, event in enumerate(events[:-1]):
        start = event["seconds_since_capture_launch"]
        following = events[index + 1]
        end = following["seconds_since_capture_launch"]
        if end <= start:
            continue
        hot = defaultdict(lambda: [0.0, 0.0])
        for begin, stop, self_spans in spans:
            filename = begin["args"]["filename"]
            if not filename:
                continue
            overlap = min(end, stop / 1_000_000 + offset) - max(start, begin["ts"] / 1_000_000 + offset)
            if overlap > 0:
                key = (str(begin["pid"]), begin["name"], filename, begin["args"]["line"])
                hot[key][0] += overlap
                hot[key][1] += sum(max(0, min(end, segment_end / 1_000_000 + offset)
                                         - max(start, segment_start / 1_000_000 + offset))
                                   for segment_start, segment_end in self_spans)
        cpu = []
        for pid, before in event.get("cpu", {}).items():
            after = following.get("cpu", {}).get(pid)
            if after is not None and after["start_ticks"] == before["start_ticks"]:
                elapsed_cpu = max(0, after["cpu_seconds"] - before["cpu_seconds"])
                cpu.append({"pid": pid, "command": before["command"], "cpu_seconds": elapsed_cpu,
                            "average_cpu_percent": elapsed_cpu / (end - start) * 100})
        result["phases"].append({"label": event["label"], "video_start_seconds": start,
            "video_end_seconds": end, "cpu": sorted(cpu, key=lambda item: item["cpu_seconds"], reverse=True),
            "hot_sampled_frames": [{"pid": key[0], "function": key[1], "filename": key[2], "line": key[3],
                                    "inclusive_sampled_wall_seconds": seconds[0], "self_sampled_wall_seconds": seconds[1]}
                                   for key, seconds in sorted(hot.items(), key=lambda item: item[1][1], reverse=True)[:20]],
            "visible_stall_assessment": "unreviewed; correlate with phase video and actual frames"})
    (output / "profile-review.json").write_text(json.dumps(result, indent=2) + "\n")
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


def review_recording(args):
    """Encode retained capture intervals after its native journey retires."""
    output = args.review_recording.expanduser().resolve()
    if not output.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
        raise ValueError("Review requires an owned persistent scratch recording")
    capture = json.loads((output / "receipt.json").read_text())
    if not capture["capture_completed"]:
        raise ValueError("The source capture did not complete")
    owner = ProcessOwner()
    receipt = {"capture_receipt": str(output / "receipt.json"), "assessment": "unreviewed",
               "completed": False}
    try:
        names = InlineReviewTiming.generate(output, args, os.environ.copy(), owner, capture["review_intervals"])
        receipt["artifacts"] = {name: {"bytes": (output / name).stat().st_size,
                                      "sha256": digest(output / name)} for name in names}
        if any(item["bytes"] == 0 for item in receipt["artifacts"].values()):
            raise RuntimeError("Empty review artifact")
        receipt["completed"] = True
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        receipt["cleanup"] = owner.cleanup()
        if receipt["cleanup"]["remaining_owned_pids"] or receipt["cleanup"]["errors"]:
            receipt["completed"] = False
        (output / "review-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if not receipt["completed"]:
        raise RuntimeError("Review cleanup incomplete; inspect review-receipt.json")
    return output


def capture_loaded_state(output, name, identity, owner, env, *, timeout, screen=False):
    """Use the existing live exporter for the exact owned UI launch identity."""
    if not identity.alive():
        raise RuntimeError("UI identity exited before state capture")
    helper = Path(__file__).resolve().parents[2] / "tools/performance/capture_live.py"
    epoch = float(env["TOAD_VIDEO_EPOCH"])
    observation = {"started_seconds": time.monotonic() - epoch}
    try:
        with (output / f"{name}-capture.log").open("w") as log:
            owner.run([sys.executable, str(helper), "--pid", str(identity.pid),
                       "--output-dir", str(output), "--name", name,
                       "--state", "--sudo", *(["--screen"] if screen else [])], env,
                      stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        observation["manifest"] = json.loads((output / f"{name}-manifest.json").read_text())
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        # Retain the actual video even when diagnostic attachment fails.
        observation["error"] = f"{type(error).__name__}: {error}"
    observation["finished_seconds"] = time.monotonic() - epoch
    return observation


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
    target = args.capture_target.admit(args, command, env)
    private_root = target.root
    selection = target.selection
    env["TOAD_VIDEO_CAPTURE_TARGET"] = target.declared_name
    selection.apply_environment(env)
    if selection.bin_directory.parent.resolve() != Path(sys.prefix).resolve():
        raise ValueError("Run recorder with the selected installed runtime's Python")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "owner": args.owner, "purpose": "installed TUI physical interaction video review",
        "output": str(output), "command": command, "terminal_command": ["st", "-e", *command],
        "fps": args.fps, "screen": [args.width, args.height],
        "profiling_requested": args.profile,
        "state_capture_requested": args.capture_state,
        "private_root": str(private_root),
        "capture_target": target.declared_name,
        "physical_journey": args.journey.declared_name,
        "original_owner_before": target.observe(),
        "recorder_argv": sys.argv,
        "recorder_source_sha256": digest(Path(__file__)),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "assessment": "unreviewed", "capture_completed": False, "completed": False,
        "review_timing": args.review_timing.declared_name,
        "review": {"start_seconds": args.review_start, "seconds": args.review_seconds,
                   "fps": args.review_fps, "frames_limit": args.review_frames,
                   "slowdown": args.slowdown, "timestamp_basis": "source video seconds"},
    }
    env["TOAD_VIDEO_OUTPUT"] = str(output)
    env["TOAD_VIDEO_MARK_SNAPSHOTS"] = "1"
    from agent_comms.registration import Registration
    registration = Registration(private_root / "registry.json")
    owner = ProcessOwner(registration)
    capture = terminal = None
    transferred_terminal = None
    transferred_program = None
    terminal_pid = None
    window = None
    try:
        with ExitStack() as stack:
            receipt["runtime_before"] = selection.receipt(owner, env, command)
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
            if args.profile:
                profiler = shutil.which("py-spy")
                if profiler is None:
                    raise RuntimeError("Optional profiling needs the existing py-spy installation")
                env["TOAD_VIDEO_PROFILE_RATE"] = str(args.profile_rate)
                env["TOAD_VIDEO_PROFILE_SAMPLING"] = args.profile_sampling.declared_name
                env["TOAD_VIDEO_PROFILE_THREADS"] = args.profile_threads.declared_name
                env["TOAD_VIDEO_PROFILE_DURATION"] = str(math.ceil(args.max_duration + 30))
                argv = [sys.executable, str(Path(__file__).resolve()), "--profile-launch", *command]
                receipt["profiler"] = {"command": argv, "executable_sha256": digest(Path(profiler)),
                                      "launch_monotonic": time.monotonic()}
                terminal = owner.start(argv, env=env,
                    stdout=stack.enter_context((output / "profiler.log").open("w")),
                    stderr=stack.enter_context((output / "terminal.log").open("w")))
                deadline = time.monotonic() + 10
                launch = output / "profile-launch.json"
                while not launch.exists() and terminal.process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.05)
                if not launch.exists():
                    raise RuntimeError("Profiled installed launcher failed; inspect profiler/terminal logs")
                receipt["profiler"]["launch"] = json.loads(launch.read_text())
                terminal_pid = receipt["profiler"]["launch"]["terminal_pid"]
                transferred_terminal = owner.transfer(terminal_pid, receipt["profiler"]["launch"]["terminal_start_ticks"])
                transferred_program = owner.transfer(receipt["profiler"]["launch"]["ui_pid"],
                                                     receipt["profiler"]["launch"]["ui_start_ticks"])
                while time.monotonic() < deadline and terminal.process.poll() is None:
                    if "Sampling process" in (output / "profiler.log").read_text():
                        break
                    time.sleep(.05)
                if "Sampling process" not in (output / "profiler.log").read_text():
                    raise RuntimeError("Profiler failed to sample the installed UI PID")
                receipt["profiler"]["sampling_ready_observed_monotonic"] = time.monotonic()
            else:
                terminal = owner.start(["st", "-e", *command], env=env,
                    stderr=stack.enter_context((output / "terminal.log").open("w")))
                terminal_pid = terminal.process.pid
                transferred_program = terminal_program(owner, terminal.child.identity, time.monotonic() + 10)
            receipt["ui_identity"] = {"pid": transferred_program.child.identity.pid,
                                      "start_ticks": transferred_program.child.identity.start_time}
            if args.capture_state:
                from agent_comms.field_codec import FieldCodec
                env["TOAD_VIDEO_UI_IDENTITY"] = json.dumps(FieldCodec.encode(transferred_program.child.identity))
            env["TOAD_VIDEO_TERMINAL"] = str(terminal_pid)
            window = owner.run(["xdotool", "search", "--sync", "--pid", str(terminal_pid)], env,
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
            env["TOAD_VIDEO_DEADLINE"] = str(deadline)
            receipt["capture_launch_monotonic"] = started
            receipt["terminal_pid"] = terminal_pid
            print(f"Recording isolated display {env['DISPLAY']}: {output}", flush=True)

            def remaining():
                seconds = deadline - time.monotonic()
                if seconds <= 0:
                    raise TimeoutError("Recording interaction budget exhausted")
                return seconds

            def screenshot(name):
                owner.run(["import", "-display", env["DISPLAY"], "-window", "root", str(output / name)],
                          env, timeout=min(10, remaining()))

            def capture_state(name):
                if not args.capture_state:
                    return
                receipt.setdefault("state_captures", {})[name] = capture_loaded_state(
                    output, name, transferred_program.child.identity, owner, env, timeout=remaining(), screen=True)

            time.sleep(min(args.startup_wait, remaining()))
            screenshot("before.png")
            capture_state("before")
            receipt["terminal_processes"] = {str(identity.pid): {"start_ticks": identity.start_time,
                "command": Path(f"/proc/{identity.pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")}
                for group in (transferred_terminal or terminal, transferred_program)
                for identity in group.members() if Path(f"/proc/{identity.pid}/cmdline").exists()}
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
            if terminal.process.poll() is not None or not transferred_program.child.identity.alive():
                raise RuntimeError(f"Installed terminal exited during recording: {terminal.process.returncode}")
            screenshot("after.png")
            capture_state("after")
            receipt["duration_seconds"] = time.monotonic() - started
            capture.stop(signal.SIGINT)
            receipt["capture_returncode"] = capture.process.returncode
            if capture.process.returncode not in (0, 255):
                raise RuntimeError(f"Video recorder exited {capture.process.returncode}")
            receipt["capture_completed"] = True
            receipt["runtime_after"] = selection.receipt(owner, env, command)
            receipt["runtime_unchanged"] = receipt["runtime_before"] == receipt["runtime_after"]
            # Quit through the installed application; persistent owners are excluded.
            owner.run(["xdotool", "key", "--window", window, "ctrl+q"], env, timeout=2)
            try:
                terminal.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            if args.profile and terminal.process.poll() is None:
                terminal.send_signal(signal.SIGINT)
                try:
                    terminal.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            transferred_program.stop()
            if transferred_terminal is not None:
                transferred_terminal.stop()
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
            if args.profile:
                receipt["profile_review"] = profile_review(output, receipt, args.profile_rate)
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
            if args.capture_state:
                names.extend(path.name for name in ("before", "after", "phase")
                             for path in output.glob(f"{name}-*") if path.is_file() and path.stat().st_size)
            if args.profile:
                names.extend(["cpu-profile.json", "profile-review.json", "profile-launch.json", "profile-terminal.json", "profiler.log"])
            names.extend(args.review_timing.generate(output, args, env, owner, receipt["review_intervals"]))
            receipt["artifacts"] = {name: {"bytes": (output / name).stat().st_size,
                                         "sha256": digest(output / name)} for name in names}
            if any(item["bytes"] == 0 for item in receipt["artifacts"].values()):
                raise RuntimeError("Empty recording artifact")
            receipt["completed"] = True
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        transfer = output / "profile-terminal.json"
        if args.profile and transfer.exists():
            try:
                identity = json.loads(transfer.read_text())
                if transferred_terminal is None:
                    transferred_terminal = owner.transfer(identity["pid"], identity["start_ticks"])
                if transferred_program is None and "program" in identity:
                    program = identity["program"]
                    transferred_program = owner.transfer(program["pid"], program["start_ticks"])
            except (OSError, ValueError, KeyError) as error:
                receipt["terminal_transfer_error"] = str(error)
                receipt["completed"] = False
        if capture is not None:
            try:
                capture.stop(signal.SIGINT)
            except (OSError, subprocess.SubprocessError) as error:
                receipt["capture_cleanup_error"] = str(error)
        receipt["cleanup"] = owner.cleanup()
        try:
            receipt["original_owner_after"] = target.observe()
        except (OSError, ValueError) as error:
            receipt["original_owner_error"] = str(error)
            receipt["completed"] = False
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
    if os.environ.get("TOAD_VIDEO_TERMINAL"):
        event["cpu"] = cpu_snapshot(int(os.environ["TOAD_VIDEO_TERMINAL"]))
    if os.environ.get("TOAD_VIDEO_MARK_SNAPSHOTS") == "1":
        owner = ProcessOwner()
        try:
            name = f"phase-{label}.png"
            owner.run(["import", "-display", display, "-window", "root", str(output / name)],
                      os.environ.copy(), timeout=5)
            event["screenshot"] = name
            if os.environ.get("TOAD_VIDEO_UI_IDENTITY"):
                from agent_comms.child_process import ProcessIdentity
                from agent_comms.field_codec import FieldCodec
                identity = FieldCodec.decode(ProcessIdentity, json.loads(os.environ["TOAD_VIDEO_UI_IDENTITY"]))
                remaining = float(os.environ["TOAD_VIDEO_DEADLINE"]) - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Recording diagnostic budget exhausted")
                event["state_capture"] = capture_loaded_state(
                    output, f"phase-{label}", identity, owner, os.environ.copy(), timeout=remaining)
        finally:
            owner.cleanup()
    with (output / "events.jsonl").open("a") as target:
        target.write(json.dumps(event) + "\n")
    print(json.dumps(event), flush=True)


def marker_command():
    # Literal quoted paths avoid native xdotool stdin variable-expansion defects.
    return f"exec --sync {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} --mark "


def scroll_script(*, idle_seconds: float = 4):
    marker = marker_command()
    return "\n".join([
        "mousemove --sync 700 260", "click 1", marker + "focused", "sleep 1",
        marker + "up", "keydown Prior", "sleep 4", "keyup Prior", marker + "up-done",
        marker + "down", "keydown Next", "sleep 4", "keyup Next", marker + "down-done",
        marker + "reverse", "keydown Prior", "sleep 4", "keyup Prior", marker + "reverse-done",
        marker + "end", "key End", "sleep 1", marker + "idle", f"sleep {idle_seconds:g}", marker + "idle-done", "",
    ])


def main():
    if sys.argv[1:] == ["--runtime-probe"]:
        print(json.dumps(runtime_probe()))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--mark":
        mark(sys.argv[2])
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "--profile-launch":
        profile_launch(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    parser.add_argument("--output", type=Path, default=Path.home() / ".cache/agent-scratch/toad-video" / stamp)
    parser.add_argument("--owner", default="installed-tui-video-tools", help="Owner retaining/cleaning this evidence")
    parser.add_argument("--private-root", type=Path, help="Existing matched fixture root; active bus capture refused")
    parser.add_argument("--capture-target", type=CaptureTarget.decode, default=PrivateCapture,
                        help="Authorized launch target: " + ", ".join(CaptureTarget.names()))
    parser.add_argument("--actions", type=Path, help="Native xdotool stdin script with real clicks/keys/sleeps")
    parser.add_argument("--journey", type=PhysicalJourney.decode, default=ScrollJourney,
                        help="Canonical physical journey: " + ", ".join(PhysicalJourney.names()))
    parser.add_argument("--write-journey-script", type=Path, help="Write the selected canonical physical script, then exit")
    parser.add_argument("--close-tab-x", type=int, default=294, help="Verified saved tab close control X coordinate")
    parser.add_argument("--close-tab-y", type=int, default=40, help="Verified saved tab close control Y coordinate")
    parser.add_argument("--other-agent-x", type=int, default=180, help="Verified existing peer roster X coordinate")
    parser.add_argument("--other-agent-y", type=int, default=240, help="Verified existing peer roster Y coordinate")
    parser.add_argument("--return-tab-x", type=int, default=225, help="Verified original tab X coordinate")
    parser.add_argument("--reopen-agent-x", type=int, default=180, help="Verified original agent roster X coordinate")
    parser.add_argument("--reopen-agent-y", type=int, default=200, help="Verified original agent roster Y coordinate")
    parser.add_argument("--navigation-settle-seconds", type=float, default=2,
                        help="Physical navigation observation interval within the capture deadline")
    parser.add_argument("--scroll-idle-seconds", type=float, default=4,
                        help="Stationary observation in the shared scroll script; use15 for the original-history delayed-blank reproducer")
    parser.add_argument("--review-phase", action="append", default=[], help="Also review this native script marker (up to 8)")
    parser.add_argument("--review-recording", type=Path, help="Encode a retained capture; no UI, ACP or native process launches")
    parser.add_argument("--review-timing", type=ReviewTiming.decode, default=InlineReviewTiming,
                        help="Clip encoding lifetime: " + ", ".join(ReviewTiming.names()))
    parser.add_argument("--profile", action="store_true", help="Sample actual UI and Python workers with installed py-spy")
    parser.add_argument("--capture-state", action="store_true",
                        help="Export loaded DTOs/SVG at before/after and physical phase markers using capture_live --sudo")
    parser.add_argument("--profile-rate", type=int, default=25, help="Bounded sampling rate (10-49 Hz)")
    parser.add_argument("--profile-sampling", type=ProfileSampling.decode, default=ConsistentSampling,
                        help="Stack read policy: " + ", ".join(ProfileSampling.names()))
    parser.add_argument("--profile-threads", type=ThreadSampling.decode, default=AllThreadSampling,
                        help="Thread selection: " + ", ".join(ThreadSampling.names()))
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
    if not math.isfinite(args.scroll_idle_seconds) or not 0 < args.scroll_idle_seconds < args.max_duration:
        parser.error("Scroll idle observation must be positive and shorter than capture duration")
    if not (all(0 <= value < args.width for value in
                (args.close_tab_x, args.other_agent_x, args.return_tab_x, args.reopen_agent_x))
            and all(0 <= value < args.height for value in
                    (args.close_tab_y, args.other_agent_y, args.reopen_agent_y))):
        parser.error("Navigation coordinates must be within the isolated recording screen")
    if not math.isfinite(args.navigation_settle_seconds) or not 0 < args.navigation_settle_seconds < args.max_duration:
        parser.error("Navigation observation must be positive and shorter than capture duration")
    if args.write_journey_script:
        destination = args.write_journey_script.expanduser().resolve()
        if not destination.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
            parser.error("Scroll script must be under persistent agent scratch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x") as target:
            target.write(args.journey.script(args))
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
    bounds = {"profile_rate": (10, 49), "fps": (1, 120), "width": (320, 1920), "height": (240, 1200),
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
    print(review_recording(args) if args.review_recording else record(args))


if __name__ == "__main__":
    main()
