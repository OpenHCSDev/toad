#!/usr/bin/env python3
"""Record real installed terminal output without touching the desktop display."""
from __future__ import annotations

import argparse
from abc import abstractmethod
from contextlib import ExitStack, contextmanager
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
import threading
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

    @classmethod
    @abstractmethod
    def observe(cls, output, args, env, owner, label): ...


class InlineReviewTiming(ReviewTiming):
    @classmethod
    def observe(cls, output, args, env, owner, label):
        return live_review(output, args, env, owner, label)

    @classmethod
    def generate(cls, output, args, env, owner, intervals, *, prefix=""):
        names = []
        for interval in intervals:
            label = interval["label"]
            label = prefix + label if prefix else (None if label == "main" else label)
            print(f"Preparing review {label or 'main'} at {interval['start']:.3f}s for {interval['seconds']:.3f}s", flush=True)
            artifacts(output, args, env, owner, start=interval["start"], seconds=interval["seconds"], label=label, consecutive=True)
            names.extend([f"{label}-slow.mp4", f"{label}-frames.png"] if label else ["slow.mp4", "frames.png"])
        return names


class DeferredReviewTiming(ReviewTiming):
    @classmethod
    def observe(cls, output, args, env, owner, label):
        return {"label": label,
                "assessment": "Clip encoding deferred; native frame tracing remains active. "
                              "Inspect consecutive original video frames during or after the run."}

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

    def stop(self, sig=signal.SIGTERM, *, grace_seconds=3):
        self.send_signal(sig)
        deadline = time.monotonic() + grace_seconds
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
        self.process.poll()
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


class ProfileProcess(OwnedProcess):
    """Finish the owned sampling process before retiring its UI target."""

    export_seconds = 8

    def stop(self, sig=signal.SIGINT):
        return super().stop(sig, grace_seconds=self.export_seconds)

    def export(self, output, receipt):
        started = time.monotonic()
        remaining = self.stop()
        path = output / "cpu-profile.json"
        receipt["profile_export"] = {
            "started_monotonic": started, "finished_monotonic": time.monotonic(),
            "returncode": self.process.returncode, "remaining_owned_pids": remaining,
            "bytes": path.stat().st_size if path.exists() else 0,
        }
        if remaining or self.process.returncode != 0 or not receipt["profile_export"]["bytes"]:
            raise RuntimeError("Owned profiler failed to export; inspect profile_export and profiler.log")


class ProcessOwner:
    """One launcher/timeout/cleanup mechanism for all recorder subprocesses."""

    def __init__(self, registration: Registration | None = None):
        self.children = []
        self.registration = registration

    def start(self, argv, *, before_start=None, process_type=OwnedProcess, **kwargs):
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
        owned = process_type(child, self.registration)
        owned.text = text
        self.children.append(owned)
        return owned

    def transfer(self, pid, start_ticks):
        from agent_comms.child_process import ObservedProcess, ProcessIdentity
        owned = TransferredGroup(ObservedProcess(ProcessIdentity(pid, start_ticks)), self.registration)
        self.children.append(owned)
        return owned

    @contextmanager
    def finalizing(self):
        """Finish owned teardown and its receipt after the first interruption.

        The interrupted operation still fails. A further terminal interrupt
        cannot abandon the original child groups halfway through their cleanup.
        Signal handlers belong to this synchronous shutdown lifetime only.
        """
        # Python delivers these handlers on the main thread. Existing asyncio
        # driver wrappers also use this owner in worker threads; those threads
        # finish teardown normally and cannot install process signal handlers.
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        handlers = {sig: signal.signal(sig, signal.SIG_IGN)
                    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        try:
            yield
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)

    def run(self, argv, env, *, timeout=30, stdout=subprocess.DEVNULL,
            observe=None, observation_interval=1, **kwargs):
        owned = self.start(argv, env=env, stdout=stdout, **kwargs)
        try:
            deadline = time.monotonic() + timeout
            while True:
                # Observation may outlast the command. Let its original
                # process/pipe owner report completion even after that delay;
                # a deadline alone cannot turn an exited child into a timeout.
                remaining = max(0, deadline - time.monotonic())
                try:
                    out, err = owned.process.communicate(
                        timeout=min(remaining, observation_interval) if observe else remaining)
                    break
                except subprocess.TimeoutExpired:
                    if observe is None or time.monotonic() >= deadline:
                        raise
                    observe()
            if owned.text:
                out = out.decode() if out is not None else None
                err = err.decode() if err is not None else None
            if owned.process.returncode:
                raise subprocess.CalledProcessError(owned.process.returncode, argv, out, err)
            return subprocess.CompletedProcess(argv, owned.process.returncode, out, err)
        finally:
            with self.finalizing():
                owned.stop()

    def cleanup(self):
        leaks, errors = [], []
        with self.finalizing():
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
        from agent_comms.private_nk_entrypoint import private_nk_from_environment
        launch = private_nk_from_environment()
        if launch is not None:
            result["native_launch"] = {"root": str(launch.validated_root),
                "wire_root_id": launch.wire_root_id,
                "native_package": str(launch.native_package.resolve())}
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

    def publish_verified_stage(self, staging_receipt, owner, env, command):
        """Publish a verified cohort and require the existing recorder preflight.

        This artifact records immutable package identity. Live activation belongs
        to the canonical route and launcher, never to this metadata's state.
        """
        verified = json.loads(Path(staging_receipt).read_text())
        stage = self.bin_directory.parent.resolve()
        if Path(verified["stage"]).resolve() != stage:
            raise ValueError("Verified staging receipt belongs to another candidate")
        activation = {
            key: verified[key] for key in ("stage", "pins", "sdk", "native_package")
        }
        activation["state"] = "verified-immutable-cohort"
        activation["staging_receipt_sha256"] = digest(Path(staging_receipt))
        pending = stage / ".activation.json.pending"
        pending.write_text(json.dumps(activation, indent=2) + "\n")
        pending.replace(stage / "activation.json")
        return self.receipt(owner, env, command)

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
        launch = result["observed"].get("native_launch")
        if launch is not None:
            native = result.get("activation", {}).get("native_package")
            if not native or Path(native).resolve() != Path(launch["native_package"]):
                raise ValueError("Candidate activation and actual ACP native launch must match")
        return result


class PhysicalJourney(DeclaredFamily, affix="Journey"):
    """Declare bounded physical journeys; submission needs its original capability."""

    review_artifacts = ()
    motion_phases = ()

    @classmethod
    def review_intervals(cls, args, events, duration):
        """Select real gesture intervals from the journey's original markers."""
        labels = args.review_phase or cls.motion_phases
        indexed = {event["label"]: index for index, event in enumerate(events)}
        missing = set(args.review_phase) - indexed.keys()
        if missing:
            raise ValueError("Missing native script markers: " + ", ".join(sorted(missing)))
        intervals = []
        for label in labels:
            if label not in indexed:
                continue  # A failed capture may stop before a later gesture.
            index = indexed[label]
            start = events[index]["seconds_since_capture_launch"]
            end = events[index + 1]["seconds_since_capture_launch"] if index + 1 < len(events) else duration
            seconds = min(args.review_seconds, end - start, duration - start)
            if seconds > 0:
                intervals.append({"label": label, "start": start, "seconds": seconds})
        if not intervals:
            seconds = min(args.review_seconds, duration - args.review_start)
            if seconds <= 0:
                raise ValueError("Review start lies outside the recorded video")
            intervals.append({"label": "main", "start": args.review_start, "seconds": seconds})
        return intervals

    @classmethod
    def opening_commands(cls, args):
        # Use the application's idempotent reveal binding before requesting
        # painted roster targets. A collapsed sidebar has no clickable rows.
        return ("key ctrl+b", f"sleep {args.navigation_settle_seconds:g}",
                marker_command() + "sidebar-revealed")

    @classmethod
    @abstractmethod
    def script(cls, args): ...

    @classmethod
    def authorize(cls, target, args):
        if args.fresh_input is not None:
            raise ValueError("This physical journey does not submit native inputs")

    @classmethod
    def actions(cls, args):
        script = cls.script(args)
        if args.actions is not None and args.actions.read_text() != script:
            raise ValueError("Actions must match the selected canonical physical journey")
        return script

    @classmethod
    def review(cls, output, receipt):
        return None

    @classmethod
    def validate_review(cls, review):
        """The journey owns required native checks; footage review stays separate."""


class ObserveJourney(PhysicalJourney):
    """Record stationary output without executing physical input."""

    @classmethod
    def script(cls, args):
        return ""


class ArchiveJourney(PhysicalJourney):
    """Open retained sessions using original native controls, without input."""

    @classmethod
    def opening_commands(cls, args):
        if not args.capture_state:
            raise ValueError("Archive controls require native state capture")
        if not 0 <= args.archive_index < 111:
            raise ValueError("Archive index must be within the retained 111-row fixture")
        marker = marker_command()
        state = lambda label: str(args.output.resolve() / f"phase-{label}-state.pickle")
        return (
            "key ctrl+g", "sleep 2", marker + "archive-feed",
            native_click_command(state("archive-feed"), target="widget", name="Button#historical-sessions"),
            "sleep 1", marker + "archive-modal",
            native_click_command(state("archive-modal"), target="widget", name="Select#saved-identity"),
            "sleep 1", marker + "archive-selector --image-only",
            "key Home", *("key Down" for _ in range(args.archive_index)), "key Return",
            "sleep 3", marker + "archive-native",
            native_click_command(state("archive-native"), target="widget", name="HistoryWindow#saved-window"),
            "sleep .2", marker + "archive-focused",
        )

    @classmethod
    def script(cls, args):
        marker = marker_command()
        return "\n".join((*cls.opening_commands(args), "key End", "sleep 1",
                          marker + "archive-end", "key Escape", "sleep 1",
                          marker + "archive-return")) + "\n"


class ArchiveScrollJourney(ArchiveJourney):
    """Hold the original gestures on the selected certified Saved history."""

    @classmethod
    def script(cls, args):
        marker = marker_command()
        return "\n".join((*cls.opening_commands(args),
                          scroll_gestures(idle_seconds=args.scroll_idle_seconds,
                                          hold_seconds=args.scroll_hold_seconds),
                          "key Escape", "sleep 1", marker + "archive-return")) + "\n"


class ScrollJourney(PhysicalJourney):
    motion_phases = ("up", "down", "reverse", "end")

    @classmethod
    def script(cls, args):
        if not args.capture_state:
            raise ValueError("Scrolling requires --capture-state for the native history focus target")
        return scroll_script(idle_seconds=args.scroll_idle_seconds, hold_seconds=args.scroll_hold_seconds)


class WarmScrollJourney(ScrollJourney):
    """Use one scroll journey and actual A/B/A clicks to observe retained resources."""

    draft_suffix = "warm-scroll-draft"
    review_artifacts = ("warm-scroll-review.json",)
    scroll_review_phases = ("focused", "up-done", "down-done", "reverse-done")

    @classmethod
    def paging_commands(cls, args):
        return ()

    @classmethod
    def history_commands(cls, args):
        return (scroll_script(idle_seconds=args.scroll_idle_seconds,
                              hold_seconds=args.scroll_hold_seconds,
                              state="phase-draft-state.pickle"),)

    @classmethod
    def closing_commands(cls, args):
        return ()

    @classmethod
    def ready_command(cls, args, label, thread):
        return (marker_command() + f"{label} --wait-history-seconds {args.history_wait_seconds:g} "
                f"--wait-history-interval {args.history_wait_interval:g} "
                f"--wait-history-thread {shlex.quote(thread)}")

    @classmethod
    def peer_click(cls, args):
        if not args.peer_thread:
            raise ValueError("Warm scrolling requires --peer-thread for the actual native roster target")
        return native_click_command("phase-switch-b-state.pickle", target="thread", name=args.peer_thread)

    @classmethod
    def peer_ready(cls, args):
        if not args.peer_thread:
            raise ValueError("Warm scrolling requires the intended peer identity")
        return cls.ready_command(args, "b-open", args.peer_thread)

    @classmethod
    def script(cls, args):
        if not args.capture_state:
            raise ValueError("Warm scrolling requires --capture-state")
        peer_click, peer_ready = cls.peer_click(args), cls.peer_ready(args)
        state_home = Path(os.environ["XDG_STATE_HOME"]).resolve()
        if not state_home.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
            raise ValueError("Warm draft editing requires a copied private UI state under agent scratch")
        marker = marker_command()
        settle = f"sleep {args.navigation_settle_seconds:g}"
        return "\n".join([
            *cls.opening_commands(args),
            marker + "warm-start", native_click_command("phase-warm-start-state.pickle", target="editor"),
            f"type --clearmodifiers --delay 80 {cls.draft_suffix}", settle, marker + "draft",
            *cls.paging_commands(args),
            *cls.history_commands(args),
            marker + "switch-b", peer_click, peer_ready, marker + "return-a",
            native_click_command("phase-return-a-state.pickle", target="original_tab",
                                 original_state="phase-warm-start-state.pickle"), settle, marker + "a-return",
            native_click_command("phase-a-return-state.pickle", target="editor"), "key ctrl+z", settle,
            marker + "undo", *cls.closing_commands(args), "",
        ])

    @classmethod
    def review(cls, output, receipt):
        from scroll_observation import review_warm_return
        return review_warm_return(output, receipt, suffix=cls.draft_suffix,
                                  scroll_labels=cls.scroll_review_phases)

    @classmethod
    def validate_review(cls, review):
        failed = [name for name, passed in review["checks"].items() if not passed]
        if failed:
            raise RuntimeError("Warm scroll native journey failed: " + ", ".join(failed))
        if review["unavailable_scroll_phases"]:
            raise RuntimeError("Warm scroll observation incomplete: "
                               + ", ".join(review["unavailable_scroll_phases"]))


class RetainedLifetimeJourney(WarmScrollJourney):
    """Original saved view custody through scroll, actual A/B/A and End.

    This qualifies source/application lifetime, not paging velocity or FPS.
    """

    review_artifacts = ("retained-lifetime-review.json",)

    @classmethod
    def opening_commands(cls, args):
        return (cls.ready_command(args, "warm-ready", args.command[-1]),
                *super().opening_commands(args))

    @classmethod
    def history_commands(cls, args):
        return (native_click_command("phase-draft-state.pickle"), "key Prior",
                f"sleep {args.navigation_settle_seconds:g}", marker_command() + "reader-before-return")

    @classmethod
    def closing_commands(cls, args):
        return (native_click_command("phase-undo-state.pickle"), "key End",
                f"sleep {args.navigation_settle_seconds:g}", marker_command() + "lifetime-end")

    @classmethod
    def review(cls, output, receipt):
        from scroll_observation import review_retained_lifetime
        return review_retained_lifetime(output, receipt, suffix=cls.draft_suffix)


class WarmSourceJourney(WarmScrollJourney):
    """Use the same physical journey with two real source workspace tabs."""

    @classmethod
    def peer_click(cls, args):
        return native_click_command("phase-switch-b-state.pickle", target="peer_tab",
                                    original_state="phase-warm-start-state.pickle")


class ScrollTravelRegressionJourney(ScrollJourney):
    """Discriminate focused key delivery and native travel on one saved source."""

    motion_phases = ("input-held-up", "history-held-up", "end-done")

    @classmethod
    def input_commands(cls, args):
        marker = marker_command()
        return [marker + "input-held-up", "keydown Prior",
                f"sleep {args.scroll_hold_seconds:g}", "keyup Prior",
                marker + "input-held-up-done"]

    @classmethod
    def script(cls, args):
        if not args.capture_state or not args.scroll_travel:
            raise ValueError("Travel regression requires native state and travel observation")
        marker = marker_command()
        ready = (marker + f"travel-start --wait-history-seconds {args.history_wait_seconds:g} "
                 f"--wait-history-interval {args.history_wait_interval:g} "
                 f"--wait-history-thread {shlex.quote(args.command[-1])}")
        hold = f"sleep {args.scroll_hold_seconds:g}"
        idle = f"sleep {args.scroll_idle_seconds:g}"
        return "\n".join([
            ready + " --require-editor-focus",
            *cls.input_commands(args), marker + "before-history-focus",
            native_click_command("phase-before-history-focus-state.pickle"),
            marker + "history-held-up", "keydown Prior", hold, "keyup Prior",
            marker + "history-held-up-done", idle, marker + "mid-history-idle-done",
            "key End", idle, marker + "end-done", "",
        ])


class InputPagingAcceptanceJourney(ScrollTravelRegressionJourney):
    """Reject absent canonical routing while observing the actual busy source."""

    review_artifacts = ("input-paging-review.json",)

    motion_phases = ("input-held-up", "input-held-down", "history-held-up")

    @classmethod
    def input_commands(cls, args):
        return [*super().input_commands(args),
                f"sleep {args.scroll_idle_seconds:g}",
                marker_command() + "input-mid-history-idle-done",
                *cls.down_commands(args)]

    @classmethod
    def down_commands(cls, args):
        marker = marker_command()
        return [marker + "input-held-down",
                "keydown Next", f"sleep {args.scroll_hold_seconds:g}", "keyup Next",
                marker + "input-held-down-done"]

    @classmethod
    def review(cls, output, receipt):
        from scroll_observation import NativePhase
        initial, up, down = (NativePhase.read(output, name) for name in
                            ("travel-start", "input-held-up-done", "input-held-down-done"))
        phases = {event["label"]: event["seconds_since_capture_launch"] for event in receipt["events"]}
        trace = [json.loads(line) for line in (output / "scroll-travel.jsonl").read_text().splitlines()]

        def routed(action, begin, end):
            start = receipt["capture_launch_monotonic"]
            return any(event["event"] == action and event["window"] == initial.window
                       and start + phases[begin] <= event["monotonic_ns"] / 1e9 < start + phases[end]
                       for event in trace)

        checks = {
            "input_remains_focused": all(phase.focused_widget == phase.editor
                                         for phase in (initial, up, down)),
            "original_editor_window_and_mode": all(
                (phase.editor, phase.window, phase.mode) == (initial.editor, initial.window, initial.mode)
                for phase in (up, down)),
            "draft_and_caret_preserved": all((phase.text, phase.selection) == (initial.text, initial.selection)
                                            for phase in (up, down)),
            "input_pageup_moves_history": up.scroll_y < initial.scroll_y or up.admits_before(initial),
            "input_pagedown_moves_history": down.scroll_y > up.scroll_y or down.admits_after(up),
            "input_pageup_reaches_original_window": routed("history_page_up", "input-held-up", "input-held-up-done"),
            "input_pagedown_reaches_original_window": routed("history_page_down", "input-held-down", "input-held-down-done"),
        }
        result = {"checks": checks, "native_checks_passed": all(checks.values()),
                  "scope": "Installed canonical input paging only; not smooth-scroll or frozen-frame acceptance",
                  "physical_assessment": "unreviewed; inspect the busy video and correlated profile"}
        (output / "input-paging-review.json").write_text(json.dumps(result, indent=2) + "\n")
        return result

    @classmethod
    def validate_review(cls, review):
        failed = [name for name, passed in review["checks"].items() if not passed]
        if failed:
            raise RuntimeError("Installed input-focused history paging failed: " + ", ".join(failed))


class InputWarmJourney(WarmScrollJourney):
    """Use the original warm journey with focused paging and idle away from tail."""

    review_artifacts = (*WarmScrollJourney.review_artifacts,
                        *InputPagingAcceptanceJourney.review_artifacts)

    motion_phases = (*InputPagingAcceptanceJourney.motion_phases, *WarmScrollJourney.motion_phases)

    @classmethod
    def opening_commands(cls, args):
        if not args.scroll_travel:
            raise ValueError("Input warm acceptance requires original paging observation")
        return (cls.ready_command(args, "warm-ready", args.command[-1]),
                *super().opening_commands(args))

    @classmethod
    def paging_commands(cls, args):
        marker = marker_command()
        return (marker + "travel-start --require-editor-focus",
                *ScrollTravelRegressionJourney.input_commands(args),
                f"sleep {args.scroll_idle_seconds:g}", marker + "input-mid-history-idle-done",
                *InputPagingAcceptanceJourney.down_commands(args))

    @classmethod
    def review(cls, output, receipt):
        return {"warm": super().review(output, receipt),
                "input": InputPagingAcceptanceJourney.review(output, receipt)}

    @classmethod
    def validate_review(cls, review):
        super().validate_review(review["warm"])
        InputPagingAcceptanceJourney.validate_review(review["input"])


class ForkCompactionJourney(InputWarmJourney):
    """One fresh configured input on the authorized fork, then original warm paging."""

    @classmethod
    def authorize(cls, target, args):
        target.authorize_input()
        if not args.fresh_input or "\n" in args.fresh_input or len(args.fresh_input) > 512:
            raise ValueError("Fork compaction requires one explicit bounded fresh input")

    @classmethod
    def opening_commands(cls, args):
        marker = marker_command()
        click = native_click_command("phase-fork-submit-ready-state.pickle", target="editor")
        return (*super().opening_commands(args), marker + "fork-submit-ready",
                click + " --empty", "type --clearmodifiers --delay 30 " + shlex.quote(args.fresh_input),
                marker + "fork-input --require-editor-focus", "key Return",
                marker + "fork-submitted")


class StationaryInputScrollJourney(ScrollJourney):
    """Observe idle feedback and editor-focused paging on the existing bus."""

    @classmethod
    def script(cls, args):
        if not args.capture_state:
            raise ValueError("Stationary/input scrolling requires native state capture")
        marker = marker_command()
        settle = f"sleep {args.navigation_settle_seconds:g}"
        ready = (marker + f"stationary-start --wait-history-seconds {args.history_wait_seconds:g} "
                 f"--wait-history-interval {args.history_wait_interval:g} "
                 f"--wait-history-thread {shlex.quote(args.command[-1])}")
        return "\n".join([
            ready, settle, marker + "stationary-loaded",
            native_click_command("phase-stationary-loaded-state.pickle"),
            "key Prior", settle, marker + "slightly-up",
            f"sleep {args.scroll_idle_seconds:g}", marker + "stationary-done",
            native_click_command("phase-stationary-done-state.pickle", target="editor"),
            marker + "input-focused", "key Prior", settle, marker + "input-pageup",
            "key Next", settle, marker + "input-pagedown",
            scroll_script(idle_seconds=args.scroll_idle_seconds,
                          hold_seconds=args.scroll_hold_seconds,
                          state="phase-input-pagedown-state.pickle"),
            "",
        ])

    @classmethod
    def review(cls, output, receipt):
        from scroll_observation import NativePhase

        labels = ("stationary-loaded", "slightly-up", "stationary-done",
                  "input-focused", "input-pageup", "input-pagedown", "idle-done")
        phases = {label: NativePhase.read(output, label) for label in labels}
        initial, offset, idle = (phases[label] for label in labels[:3])
        result = {"checks": {
            "loaded_before_pageup": initial.loaded_pages > 0 and initial.maximum > 0,
            "stationary_away_from_tail": not offset.follows_tail and not idle.follows_tail,
            "offset_reader": offset.scroll_y < offset.maximum and idle.scroll_y < idle.maximum,
            "input_keeps_focus": all(phases[label].focused_widget == phases[label].editor
                                     for label in ("input-focused", "input-pageup", "input-pagedown")),
        }, "phases": {label: vars(phase) for label, phase in phases.items()},
                  "scope": "Diagnostic coverage; frame smoothness and input paging remain observations"}
        (output / "stationary-scroll-review.json").write_text(
            json.dumps(result, default=str, indent=2) + "\n")
        return result

    @classmethod
    def validate_review(cls, review):
        failed = [name for name, passed in review["checks"].items() if not passed]
        if failed:
            raise RuntimeError("Stationary diagnostic missed its required coverage: " + ", ".join(failed))


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

    purpose = "installed TUI physical interaction video review"

    @property
    def root(self):
        return self.route.root

    @classmethod
    @abstractmethod
    def admit(cls, args, command, env): ...

    @classmethod
    @abstractmethod
    def read_route(cls, env): ...

    @abstractmethod
    def observe(self): ...

    def authorize_input(self):
        raise ValueError("This capture has no configured-provider input authority")


@dataclass(frozen=True)
class PrivateCapture(CaptureTarget):
    route: ActiveRoute
    selection: RuntimeSelection

    @classmethod
    def read_route(cls, env):
        from agent_comms.active_route import ActiveRoute
        return ActiveRoute(Path(env["AGENT_COMMS_ROOT"]), env["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"],
                           Path(env["AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE"]))

    @classmethod
    def admit_root(cls, args, env):
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
        return root

    @classmethod
    def admit(cls, args, command, env):
        root = cls.admit_root(args, env)
        selection = RuntimeSelection.from_environment(command, env)
        cls.require_acp_command(command, selection)
        route = cls.read_route(env)
        if route.observe_root() != root:
            raise ValueError("Private launch route does not name its admitted root")
        return cls(route, selection)

    @staticmethod
    def require_acp_command(command, selection):
        expected_acp = shlex.join([str(selection.bin_directory / "python"), "-m", "agent_comms.acp"])
        if (len(command) < 4 or command[1:3] != ["acp", expected_acp]
                or Path(command[0]).resolve() != (selection.bin_directory / "toad").resolve()):
            raise ValueError("Capture requires selected installed toad acp and its paired Python ACP command")

    def observe(self):
        return {"root": str(self.root), "mode": self.declared_name}


@dataclass(frozen=True)
class SourceCapture(PrivateCapture):
    """Capture an explicitly selected persistent source application journey.

    Same private route and process custody as installed captures; this never
    represents an installed-package acceptance result.
    """

    source: Path
    purpose = "source Toad physical interaction video review"

    @classmethod
    def admit(cls, args, command, env):
        root = cls.admit_root(args, env)
        selection = RuntimeSelection.from_environment(command, env)
        if len(command) != 2 or Path(command[0]).resolve() != (selection.bin_directory / 'python').resolve():
            raise ValueError('Source capture requires the selected runtime Python and one source entrypoint')
        source = Path(command[1]).resolve()
        if not source.is_file() or not source.is_relative_to(Path.home() / 'wt'):
            raise ValueError('Source capture requires an existing persistent worktree entrypoint')
        route = cls.read_route(env)
        if route.observe_root() != root:
            raise ValueError("Source launch route does not name its admitted root")
        return cls(route, selection, source)

    def observe(self):
        return {**super().observe(), 'source': str(self.source), 'source_sha256': digest(self.source),
                'boundary': 'source application journey; not installed readiness'}


@dataclass(frozen=True)
class ExistingThreadCapture(CaptureTarget):
    """Explicit authorized read-only attachment, never a fixture/native owner."""

    route: ActiveRoute
    name: str
    identity: ProcessIdentity
    selection: RuntimeSelection

    @classmethod
    def read_route(cls, env):
        from agent_comms.active_route import read_active_route
        route = read_active_route()
        if route is None:
            raise ValueError("Existing-thread capture requires the installed active route")
        return route

    @classmethod
    def admit(cls, args, command, env):
        if args.private_root is not None:
            raise ValueError("Existing-thread capture derives its root from the canonical active route")
        if len(command) != 2 or Path(command[0]).name != "toad-comms":
            raise ValueError("Existing-thread capture requires toad-comms and one explicit registered thread")
        # Match the real default launcher's environment, not a copied private
        # route or thread identity that would redirect its retained history.
        for key in ("AGENT_COMMS_ROOT", "AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID", "AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE"):
            env.pop(key, None)
        cls.attachment_environment(env)
        route = cls.read_route(env)
        _, thread = cls.capture_owner(route, command[1])
        return cls(route, thread.name, thread.require_process(), RuntimeSelection.from_environment(command, env))

    @staticmethod
    def attachment_environment(env):
        """The ACP client attaches; it never adopts its worker's process role."""
        for key in ("AGENT_COMMS_THREAD", "AGENT_COMMS_MANAGED", "PI_AGENT_ID",
                    "PI_PARENT_ID", "PI_TASK", "PI_WORKTREE", "PI_PROMPT"):
            env.pop(key, None)

    @staticmethod
    def capture_owner(route, name):
        from agent_comms.registration import Registration
        route.observe_root()
        snapshot = Registration(route.root / "registry.json").snapshot()
        thread = snapshot.require_active(name)
        identity = thread.process_identity
        if identity is None or not identity.alive():
            raise ValueError("Existing-thread capture requires an already running owner; it must not start one")
        return snapshot, thread

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


@dataclass(frozen=True)
class OwnedForkCapture(ExistingThreadCapture, PrivateCapture):
    """Authorized canonical fork: original-root custody and its actual ACP launch."""

    purpose = "configured-provider canonical application fork physical journey"

    def authorize_input(self):
        self.observe()

    @classmethod
    def admit(cls, args, command, env):
        from agent_comms.owner_launch import RetainedOwnerLaunch, RestartEnvironment
        from agent_comms.private_nk_entrypoint import PrivateNkLaunch

        if args.private_root is not None or not args.fork_thread or not args.fork_parent:
            raise ValueError("Owned fork requires explicit registered child/parent, never a private fixture root")
        route = cls.read_route(env)
        snapshot, thread = cls.capture_owner(route, args.fork_thread)
        parent = snapshot.require_active(args.fork_parent)
        if thread.parent != parent.name or thread.name == parent.name:
            raise ValueError("Selected thread is not the authorized original parent's canonical fork")
        selection = RuntimeSelection.from_environment(command, env)
        cls.require_acp_command(command, selection)
        if command[3:] != [thread.worktree, "--session", thread.name]:
            raise ValueError("Owned fork ACP must select the actual child and its original worktree")
        retained = RetainedOwnerLaunch.capture(thread, snapshot)
        runtime = RestartEnvironment.inherit(retained.environment)
        if runtime.root is None:
            raise ValueError("Retained child has no explicit native launch root")
        launch = PrivateNkLaunch.from_environment(Path(runtime.root), retained.environment)
        if launch is None:
            raise ValueError("Retained child has no configured native launch")
        launch.validate()
        if launch.validated_root.resolve() != route.observe_root() or launch.wire_root_id != route.wire_root_id:
            raise ValueError("Retained child launch does not belong to the original active root")
        # Provider credentials/settings come from the actual retained process.
        # Only the recorder's isolated UI resource locations remain local.
        capture_environment = {key: value for key, value in env.items()
            if key.startswith("TOAD_VIDEO_") or key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME",
                                                       "XDG_DATA_HOME", "AGENT_COMMS_RUNTIME_ROOT")}
        env.clear()
        env.update(retained.environment)
        env.update(capture_environment)
        for key in ("DISPLAY", "NO_COLOR", "PYTHONPATH"):
            env.pop(key, None)
        cls.attachment_environment(env)
        launch.apply_environment(env)
        return cls(route=route, name=thread.name, identity=retained.process, selection=selection)


class PrivateOwnedForkCapture(OwnedForkCapture):
    """Canonical fork custody with the existing explicit private route owner."""

    read_route = PrivateCapture.__dict__["read_route"]


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
                "minor_faults": int(fields[7]), "major_faults": int(fields[9]),
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
    """Decode py-spy's Chrome transitions once and align them with physical actions."""
    trace_path = output / "cpu-profile.json"
    if trace_path.stat().st_size > 128 * 1024 * 1024:
        raise RuntimeError("CPU profile exceeds the 128 MiB review bound")
    from profile_trace import ProfileTrace
    trace = ProfileTrace(trace_path)
    observations = tuple(trace.observations())
    launch = json.loads((output / "profile-launch.json").read_text())
    if not any(observation.pid == launch["ui_pid"] for observation in observations):
        raise RuntimeError("Profiler did not observe the actual installed UI PID")
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
                   "Chrome transitions omit unchanged stack samples; counts below are observed transition groups, not samples, calls, durations or CPU time",
                   "Threads remain separate; recursive frame identities count once per observed stack",
                   "Kernel counter deltas give per-process CPU time at action boundaries",
                   "Sampled functions identify activation/preparation/layout/paint activity; no production event hook supplies exact phase timestamps",
                   "No automatic inference that a UI frame passed or a function is redundant"],
        "processes": sorted({str(record.pid) for record in trace.records}), "phases": []}
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
        hot = defaultdict(lambda: [0, 0])
        thread_groups = defaultdict(int)
        for observation in observations:
            observed_at = observation.timestamp / 1_000_000 + offset
            if not start <= observed_at < end:
                continue
            thread_groups[observation.pid, observation.tid] += 1
            leaf = observation.frames[-1]
            for frame in set(observation.frames):
                key = (str(observation.pid), str(observation.tid), frame)
                hot[key][0] += 1
                hot[key][1] += frame == leaf
        cpu = []
        for pid, before in event.get("cpu", {}).items():
            after = following.get("cpu", {}).get(pid)
            if after is not None and after["start_ticks"] == before["start_ticks"]:
                elapsed_cpu = max(0, after["cpu_seconds"] - before["cpu_seconds"])
                cpu.append({"pid": pid, "command": before["command"], "cpu_seconds": elapsed_cpu,
                            "average_cpu_percent": elapsed_cpu / (end - start) * 100})
        result["phases"].append({"label": event["label"], "video_start_seconds": start,
            "video_end_seconds": end, "cpu": sorted(cpu, key=lambda item: item["cpu_seconds"], reverse=True),
            "observed_thread_stack_changes": [{"pid": str(pid), "tid": str(tid),
                                                "transition_groups": count}
                                               for (pid, tid), count in sorted(thread_groups.items())],
            "observed_frames": [{"pid": key[0], "tid": key[1], "function": key[2].function,
                                 "filename": key[2].filename, "line": key[2].line,
                                 "stack_presence_transition_groups": counts[0],
                                 "leaf_transition_groups": counts[1]}
                                for key, counts in sorted(hot.items(), key=lambda item: item[1][1], reverse=True)[:20]],
            "physical_evidence": {"start": phase_evidence(output, event),
                                  "end": phase_evidence(output, following)},
            "visible_stall_assessment": "unreviewed; correlate with phase video and actual frames"})
    (output / "profile-review.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def artifacts(output, args, env, owner, *, start, seconds, label=None, consecutive=False, encode_slow=True):
    video = output / "terminal.mp4"
    common = ["ffmpeg", "-nostdin", "-y", "-loglevel", "warning", "-threads", "1",
              "-filter_threads", "1", "-filter_complex_threads", "1"]
    # A live fragmented MP4 has no final seek index. Input seeking can silently
    # return earlier packets and stamp them as the requested interval. Select
    # the original decoded timestamps for both motion-review consumers.
    interval = ["-i", str(video)]
    trim = f"trim=start={start}:duration={seconds},setpts=PTS-STARTPTS,"
    slow = output / (f"{label}-slow.mp4" if label else "slow.mp4")
    sheet = output / (f"{label}-frames.png" if label else "frames.png")
    if encode_slow:
        owner.run(common + interval + [
            "-vf", trim + f"setpts={args.slowdown}*PTS", "-r", str(args.fps),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-threads", "1",
            str(slow),
        ], env, timeout=60)
    fps = args.fps if consecutive else args.review_fps
    frames = min(args.review_frames, max(1, math.ceil(seconds * fps)))
    rows = math.ceil(frames / args.sheet_columns)
    # Trimming resets PTS. Add the original source offset to the frame labels.
    stamp = r"drawtext=text='%{pts\:hms}':fontsize=14:fontcolor=white:box=1:boxcolor=black:x=4:y=4"
    filters = (trim + f"fps={fps},settb=AVTB,setpts=PTS+{start}/TB,{stamp},"
               f"scale=640:-2,tile={args.sheet_columns}x{rows}:nb_frames={frames}")
    owner.run(common + interval + ["-vf", filters, "-frames:v", "1", "-threads", "1",
                                  "-update", "1", str(sheet)], env, timeout=60)


def phase_events(output):
    """Decode the original physical phase producer for live and final review."""
    path = output / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def frame_review(output, receipt, *, window_seconds):
    """Use the original observer/analysis and recording's monotonic origin."""
    tools = Path(__file__).resolve().parents[2] / "tools/performance"
    spec = importlib.util.spec_from_file_location("analyze_trace", tools / "analyze_trace.py")
    analysis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analysis)
    traces = list(output.glob("*-state-frames.json"))
    if not traces:
        return {"available": False, "reason": "This capture has no original driver frame trace"}
    source = max(traces, key=lambda path: path.stat().st_mtime_ns)
    trace = json.loads(source.read_text())
    if not any(event["event"] == "frame_enqueued" for event in trace):
        return {"available": False, "trace": source.name,
                "reason": "No original driver enqueue events; exports do not establish frame observation"}
    origin = round(receipt["capture_launch_monotonic"] * 1e9)
    events = phase_events(output)
    actions = [{"action": before["label"],
                "start_ns": origin + round(before["seconds_since_capture_launch"] * 1e9),
                "end_ns": origin + round(after["seconds_since_capture_launch"] * 1e9)}
               for before, after in zip(events, events[1:])]
    delivery = analysis.frame_delivery(
        trace, actions, origin_ns=origin,
        end_ns=trace[-1]["ns"] if trace else origin,
        window_seconds=window_seconds)
    delivery["trace_source"] = source.name
    delivery["trace_limit"] = 100000
    delivery["trace_limit_reached"] = len(trace) == 100000
    delivery["first_observed_ns"] = trace[0]["ns"] if trace else None
    analysis.write_frame_timeline(output / "frame-delivery.json", delivery)
    return {"available": True, "trace": source.name,
            "artifacts": ["frame-delivery.json", "frame-delivery.svg"],
            "intervals": delivery["intervals"], "scope": delivery["scope"]}


def live_review(output, args, env, owner, label):
    """Expose consecutive finalized video frames while the same UI is running.

    Encoding a sheet does not attest that somebody watched it. Record the
    source interval and encoding overhead; the operator must inspect it then.
    """
    started = time.monotonic()
    info = owner.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                      "-show_packets", "-show_entries", "format=duration:packet=pts_time,flags",
                      "-of", "json", str(output / "terminal.mp4")], env,
                     stdout=subprocess.PIPE, text=True, timeout=5)
    metadata = json.loads(info.stdout)
    # A running fragmented MP4 may advertise the unfinished current GOP. The
    # last acquired keyframe starts that GOP; earlier packets are complete.
    duration = max(float(packet["pts_time"]) for packet in metadata["packets"]
                   if "K" in packet["flags"])
    seconds = min(duration, args.review_frames / args.fps)
    if seconds <= 0:
        raise RuntimeError("Live recording has no finalized video frames yet")
    start = duration - seconds
    artifacts(output, args, env, owner, start=start, seconds=seconds,
              label=label, consecutive=True, encode_slow=False)
    result = {"event": "live_review_available", "label": label,
              "source_start_seconds": start, "source_end_seconds": duration,
              "encoding_started_monotonic": started,
              "encoding_finished_monotonic": time.monotonic(),
              "frames": str(output / f"{label}-frames.png"),
              "assessment": "unreviewed; inspect consecutive frames during or after the run"}
    print(json.dumps(result), flush=True)
    return result


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
        env = os.environ.copy()
        video = output / "terminal.mp4"
        info = owner.run(["ffprobe", "-v", "error", "-show_format", "-of", "json", str(video)],
                         env, stdout=subprocess.PIPE, text=True, timeout=5)
        duration = float(json.loads(info.stdout)["format"]["duration"])
        args.fps = capture["fps"]
        journey = PhysicalJourney.decode(capture["physical_journey"])
        events = phase_events(output)
        intervals = journey.review_intervals(args, events, duration)
        receipt["source"] = {"receipt_sha256": digest(output / "receipt.json"),
                             "video_sha256": digest(video),
                             "application_completed": capture["completed"],
                             "application_error": capture.get("error")}
        receipt["intervals"] = intervals
        frame_path = output / "frame-delivery.json"
        if frame_path.exists():
            receipt["frame_review"] = {"available": True, "artifact": frame_path.name}
        else:
            receipt["frame_review"] = frame_review(output, capture, window_seconds=args.frame_window_seconds)
        profile_path = output / "profile-review.json"
        if profile_path.exists():
            profile = json.loads(profile_path.read_text())
        elif capture["profiling_requested"]:
            profile = profile_review(output, capture | {"events": events}, args.profile_rate)
        else:
            profile = {"phases": []}
        receipt["correlated_phases"] = [phase for phase in profile["phases"]
                                        if any(phase["video_start_seconds"] < interval["start"] + interval["seconds"]
                                               and phase["video_end_seconds"] > interval["start"]
                                               for interval in intervals)]
        names = InlineReviewTiming.generate(output, args, env, owner, intervals, prefix="review-")
        receipt["artifacts"] = {name: {"bytes": (output / name).stat().st_size,
                                      "sha256": digest(output / name)} for name in names}
        if any(item["bytes"] == 0 for item in receipt["artifacts"].values()):
            raise RuntimeError("Empty review artifact")
        receipt["completed"] = True
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        with owner.finalizing():
            receipt["cleanup"] = owner.cleanup()
            if receipt["cleanup"]["remaining_owned_pids"] or receipt["cleanup"]["errors"]:
                receipt["completed"] = False
            (output / "review-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if not receipt["completed"]:
        raise RuntimeError("Review cleanup incomplete; inspect review-receipt.json")
    return output


def capture_loaded_state(output, name, identity, owner, env, *, timeout, screen=False,
                         wait_history_seconds=0, wait_history_interval=.1, wait_history_thread=None,
                         scroll_travel=False, install_frame_trace=False, frames_only=False):
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
                       "--state", "--sudo", "--wait-history-seconds", str(wait_history_seconds),
                       "--wait-history-interval", str(wait_history_interval),
                       *(["--wait-history-thread", wait_history_thread] if wait_history_thread else []),
                       *(["--screen"] if screen else []),
                       *(["--frame-trace"] if env.get("TOAD_VIDEO_FRAME_TRACE") == "1" else []),
                       *(["--install-frame-trace"] if install_frame_trace else []),
                       *(["--frames-only"] if frames_only else []),
                       *(["--scroll-travel"] if scroll_travel else [])], env,
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
    args.journey.authorize(target, args)
    script = args.journey.actions(args)
    private_root = target.root
    selection = target.selection
    env["TOAD_VIDEO_CAPTURE_TARGET"] = target.declared_name
    if args.capture_state:
        env["TOAD_VIDEO_FRAME_TRACE"] = "1"
    selection.apply_environment(env)
    if selection.bin_directory.parent.resolve() != Path(sys.prefix).resolve():
        raise ValueError("Run recorder with the selected installed runtime's Python")
    output.mkdir(parents=True, exist_ok=False)
    # Physical navigation uses normal preference owners, which save on exit.
    # Preserve their initial inputs while keeping writes inside this capture.
    config_source = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "toad" / "toad.json"
    config_home = output / "ui-config"
    (config_home / "toad").mkdir(parents=True)
    config_snapshot = config_home / "toad" / "toad.json"
    if config_source.is_file():
        shutil.copy2(config_source, config_snapshot)
    env["XDG_CONFIG_HOME"] = str(config_home)
    receipt = {
        "owner": args.owner, "purpose": target.purpose,
        "output": str(output), "command": command, "terminal_command": ["st", "-e", *command],
        "fps": args.fps, "screen": [args.width, args.height],
        "profiling_requested": args.profile,
        "state_capture_requested": args.capture_state,
        "ui_config": {"source": str(config_source), "home": str(config_home),
                      "initial_sha256": digest(config_snapshot) if config_snapshot.is_file() else None},
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
                env["TOAD_VIDEO_PROFILE_DURATION"] = str(math.ceil(args.max_duration))
                argv = [sys.executable, str(Path(__file__).resolve()), "--profile-launch", *command]
                receipt["profiler"] = {"command": argv, "executable_sha256": digest(Path(profiler)),
                                      "launch_monotonic": time.monotonic()}
                terminal = owner.start(argv, env=env, process_type=ProfileProcess,
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
                "-crf", "26", "-threads", "1", "-r", str(args.fps), "-fps_mode", "cfr", "-pix_fmt", "yuv420p",
                "-g", str(args.fps), "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                str(output / "terminal.mp4"),
            ], stderr=stack.enter_context((output / "capture.log").open("w")))
            started = time.monotonic()
            finish_deadline = started + args.max_duration
            deadline = finish_deadline - args.finalize_seconds
            env["TOAD_VIDEO_EPOCH"] = str(started)
            env["TOAD_VIDEO_DEADLINE"] = str(deadline)
            receipt["capture_launch_monotonic"] = started
            receipt["interaction_deadline_monotonic"] = deadline
            receipt["finish_deadline_monotonic"] = finish_deadline
            receipt["finalize_seconds"] = args.finalize_seconds
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
                    output, name, transferred_program.child.identity, owner, env, timeout=remaining(),
                    screen=name != "observers",
                    scroll_travel=args.scroll_travel and name == "observers",
                    install_frame_trace=name == "observers",
                    frames_only=name == "observers")

            time.sleep(min(args.startup_wait, remaining()))
            screenshot("before.png")
            capture_state("before")
            if args.capture_state:
                capture_state("observers")
                setup = receipt["state_captures"]["observers"]
                if "error" in setup or any(
                        status != "complete" for status in setup["manifest"]["receipts"].values()):
                    raise RuntimeError("Native observer acquisition did not complete: " + str(setup))
            receipt["terminal_processes"] = {str(identity.pid): {"start_ticks": identity.start_time,
                "command": Path(f"/proc/{identity.pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")}
                for group in (transferred_terminal or terminal, transferred_program)
                for identity in group.members() if Path(f"/proc/{identity.pid}/cmdline").exists()}
            if script:
                (output / "actions.xdo").write_text(script)
                receipt["driver_started_seconds"] = time.monotonic() - started
                # Installed xdotool stdin mode continued after failed execs in
                # the real236 run. Each line is a checked native CLI invocation;
                # held keys remain in the owned X server between invocations.
                with (output / "driver.log").open("w") as log:
                    for action_number, line in enumerate(script.splitlines()):
                        action_argv = shlex.split(line, comments=True)
                        if action_argv:
                            reviews = receipt.setdefault("live_reviews", [])

                            def observe():
                                label = f"live-{action_number}-{len(reviews)}"
                                try:
                                    reviews.append(args.review_timing.observe(output, args, env, owner, label))
                                    if args.capture_state:
                                        capture_loaded_state(
                                            output, label, transferred_program.child.identity, owner, env,
                                            timeout=remaining(), frames_only=True)
                                        receipt["live_frame_delivery"] = frame_review(
                                            output, receipt, window_seconds=args.frame_window_seconds)
                                except (OSError, subprocess.SubprocessError, ValueError, KeyError, RuntimeError) as error:
                                    reviews.append({"label": label, "error": f"{type(error).__name__}: {error}",
                                                    "assessment": "unreviewed"})
                                    print(json.dumps(reviews[-1]), flush=True)

                            begin = time.monotonic_ns()
                            log.write(json.dumps({"event": "driver_command_started", "ns": begin,
                                                  "argv": action_argv}) + "\n")
                            log.flush()
                            try:
                                owner.run(["xdotool", *action_argv], env, stdout=log,
                                          stderr=subprocess.STDOUT,
                                          observe=observe, observation_interval=args.live_review_interval,
                                          timeout=max(.1, remaining() - args.tail_seconds - 1))
                            finally:
                                log.write(json.dumps({"event": "driver_command_finished",
                                                      "ns": time.monotonic_ns(), "begin_ns": begin,
                                                      "argv": action_argv}) + "\n")
                                log.flush()
                receipt["driver_finished_seconds"] = time.monotonic() - started
                time.sleep(min(args.tail_seconds, remaining()))
            else:
                time.sleep(min(args.tail_seconds, remaining()))
            if not transferred_program.child.identity.alive():
                raise RuntimeError(f"Installed terminal exited during recording: {terminal.process.returncode}")
            screenshot("after.png")
            capture_state("after")
            receipt["duration_seconds"] = time.monotonic() - started
            if args.profile:
                terminal.export(output, receipt)
            capture.stop(signal.SIGINT)
            receipt["capture_returncode"] = capture.process.returncode
            if capture.process.returncode not in (0, 255):
                raise RuntimeError(f"Video recorder exited {capture.process.returncode}")
            receipt["capture_completed"] = True
            # Capture completion only answers whether video was retained.
            # Requested state exports are independent application evidence.
            for name, observation in receipt.get("state_captures", {}).items():
                if "error" in observation or any(
                        status != "complete" for status in observation["manifest"]["receipts"].values()):
                    raise RuntimeError(f"Required state capture {name} did not complete: {observation}")
            receipt["runtime_after"] = selection.receipt(owner, env, command)
            receipt["runtime_unchanged"] = receipt["runtime_before"] == receipt["runtime_after"]
            # Quit through the installed application; persistent owners are excluded.
            owner.run(["xdotool", "key", "--window", window, "ctrl+q"], env, timeout=2)
            try:
                terminal.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            receipt["terminal_exit"] = (transferred_terminal or terminal).receipt()
            if not args.profile and receipt["terminal_exit"]["returncode"] != 0:
                raise RuntimeError(f"Installed terminal did not exit successfully: {receipt['terminal_exit']}")
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
            events = phase_events(output)
            receipt["events"] = events
            receipt["frame_review"] = frame_review(
                output, receipt, window_seconds=args.frame_window_seconds)
            if args.profile:
                receipt["profile_review"] = profile_review(output, receipt, args.profile_rate)
            receipt["journey_review"] = args.journey.review(output, receipt)
            receipt["review_intervals"] = args.journey.review_intervals(args, events, duration)
            names = ["terminal.mp4", "before.png", "after.png"]
            if args.capture_state:
                names.extend(path.name for name in ("before", "after", "phase")
                             for path in output.glob(f"{name}-*") if path.is_file() and path.stat().st_size)
            if args.profile:
                names.extend(["cpu-profile.json", "profile-review.json", "profile-launch.json", "profile-terminal.json", "profiler.log"])
            names.extend(args.journey.review_artifacts)
            names.extend(path.name for path in output.glob("*-click-target.json"))
            names.extend(path.name for path in output.glob("live-*-frames.png"))
            names.extend(receipt["frame_review"].get("artifacts", ()))
            names.extend(args.review_timing.generate(output, args, env, owner, receipt["review_intervals"]))
            receipt["artifacts"] = {name: {"bytes": (output / name).stat().st_size,
                                         "sha256": digest(output / name)} for name in names}
            if any(item["bytes"] == 0 for item in receipt["artifacts"].values()):
                raise RuntimeError("Empty recording artifact")
            args.journey.validate_review(receipt["journey_review"])
            receipt["completed"] = True
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        with owner.finalizing():
            # Failure must preserve raw samples too. Export while the verified UI
            # target is still alive, before reverse-order process-group cleanup.
            if args.profile and terminal is not None and "profile_export" not in receipt:
                try:
                    terminal.export(output, receipt)
                except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                    receipt["profile_export_error"] = str(error)
                    receipt["completed"] = False
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
            if terminal is not None and (not args.profile or transferred_terminal is not None):
                # Read the actual parent's exit result. Transferred observation
                # deliberately cannot invent an exit code for the profiled UI.
                receipt["terminal_exit"] = (transferred_terminal or terminal).receipt()
                if not args.profile and receipt["terminal_exit"]["returncode"] != 0:
                    receipt["completed"] = False
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


def mark(label, *, wait_history_seconds=0, wait_history_interval=.1, wait_history_thread=None,
         image_only=False, require_editor_focus=False):
    """A native xdotool exec marker; timestamps bracket actual input injection."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", label):
        raise ValueError("Invalid phase label")
    output = Path(os.environ["TOAD_VIDEO_OUTPUT"]).resolve()
    if not output.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()) or not output.is_dir():
        raise ValueError("Marker needs the recorder's persistent scratch directory")
    display = os.environ["DISPLAY"]
    if not re.fullmatch(r":[1-9][0-9]*", display):
        raise ValueError("Marker needs an isolated display")
    if wait_history_seconds and os.environ.get("TOAD_VIDEO_MARK_SNAPSHOTS") != "1":
        raise ValueError("Visible history observation requires native marker snapshots")
    if wait_history_seconds and not wait_history_thread:
        raise ValueError("Visible history observation requires the intended thread")
    if wait_history_seconds and image_only:
        raise ValueError("Visible history observation requires a state snapshot")
    event = {"label": label, "utc": datetime.now(timezone.utc).isoformat(),
             "image_only": image_only,
             "seconds_since_capture_launch": time.monotonic() - float(os.environ["TOAD_VIDEO_EPOCH"])}
    if os.environ.get("TOAD_VIDEO_TERMINAL"):
        event["cpu"] = cpu_snapshot(int(os.environ["TOAD_VIDEO_TERMINAL"]))
    if os.environ.get("TOAD_VIDEO_MARK_SNAPSHOTS") == "1":
        owner = ProcessOwner()
        try:
            if wait_history_seconds:
                from agent_comms.child_process import ProcessIdentity
                from agent_comms.field_codec import FieldCodec
                identity = FieldCodec.decode(ProcessIdentity, json.loads(os.environ["TOAD_VIDEO_UI_IDENTITY"]))
                remaining = float(os.environ["TOAD_VIDEO_DEADLINE"]) - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Recording visible-history budget exhausted")
                event["state_capture"] = capture_loaded_state(
                    output, f"phase-{label}", identity, owner, os.environ.copy(), timeout=remaining,
                    wait_history_seconds=min(wait_history_seconds, remaining),
                    wait_history_interval=wait_history_interval, wait_history_thread=wait_history_thread)
                state = output / f"phase-{label}-state.json"
                if not state.exists():
                    error_path = output / f"phase-{label}-state-error.json"
                    detail = error_path.read_text() if error_path.exists() else str(event["state_capture"])
                    raise RuntimeError("Selected visible saved history was not published: " + detail)
                event["history_wait"] = json.loads((output / f"phase-{label}-state-wait.json").read_text())
                event["utc"] = datetime.now(timezone.utc).isoformat()
                event["seconds_since_capture_launch"] = time.monotonic() - float(os.environ["TOAD_VIDEO_EPOCH"])
                if os.environ.get("TOAD_VIDEO_TERMINAL"):
                    event["cpu"] = cpu_snapshot(int(os.environ["TOAD_VIDEO_TERMINAL"]))
            name = f"phase-{label}.png"
            owner.run(["import", "-display", display, "-window", "root", str(output / name)],
                      os.environ.copy(), timeout=5)
            event["screenshot"] = name
            if os.environ.get("TOAD_VIDEO_UI_IDENTITY") and not wait_history_seconds and not image_only:
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
    if require_editor_focus:
        metadata = json.loads((output / f"phase-{label}-state.json").read_text())
        focused = metadata["screen"]["focused"]
        if focused is None or focused["class"] not in ("PromptTextArea", "ChannelTextArea"):
            raise RuntimeError("The actual selected input is not keyboard focused")
        event["verified_editor_focus"] = focused
    with (output / "events.jsonl").open("a") as target:
        target.write(json.dumps(event) + "\n")
    print(json.dumps(event), flush=True)


def marker_command():
    # Each native invocation receives literal paths, without shell evaluation.
    return f"exec --sync {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} --mark "


def native_click_command(state, *, target="history", name=None, original_state=None, focused=False):
    helper = Path(__file__).resolve().parents[2] / "tools/performance/click_history.py"
    argv = [sys.executable, str(helper), "--target", target, "--state", state]
    if name is not None:
        argv.extend(("--name", name))
    if original_state is not None:
        argv.extend(("--original-state", original_state))
    if focused:
        argv.append("--focused")
    return "exec --sync " + shlex.join(argv)


def phase_evidence(output, event):
    """Link actual phase files and attachment timing, without guessing visual success."""
    prefix = f"phase-{event['label']}"
    return {"screenshot": event.get("screenshot"), "state_capture": event.get("state_capture"),
            "native_state": f"{prefix}-state.pickle" if (output / f"{prefix}-state.pickle").exists() else None,
            "native_metadata": f"{prefix}-state.json" if (output / f"{prefix}-state.json").exists() else None}


def scroll_script(*, idle_seconds: float = 4, hold_seconds: float = 4, state="before-state.pickle"):
    return "\n".join((native_click_command(state), marker_command() + "focused", "sleep 1",
                      scroll_gestures(idle_seconds=idle_seconds, hold_seconds=hold_seconds)))


def scroll_gestures(*, idle_seconds: float = 4, hold_seconds: float = 4):
    marker = marker_command()
    hold = f"sleep {hold_seconds:g}"
    return "\n".join([
        marker + "up", "keydown Prior", hold, "keyup Prior", marker + "up-done",
        marker + "down", "keydown Next", hold, "keyup Next", marker + "down-done",
        marker + "reverse", "keydown Prior", hold, "keyup Prior", marker + "reverse-done",
        marker + "end", "key End", "sleep 1", marker + "idle", f"sleep {idle_seconds:g}", marker + "idle-done", "",
    ])


def main():
    if sys.argv[1:] == ["--runtime-probe"]:
        print(json.dumps(runtime_probe()))
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "--mark":
        marker = argparse.ArgumentParser(description="Observe an actual native phase")
        marker.add_argument("label")
        marker.add_argument("--image-only", action="store_true",
                            help="Capture actual phase image/time without optional DTO export")
        marker.add_argument("--wait-history-seconds", type=float, default=0)
        marker.add_argument("--wait-history-interval", type=float, default=.1)
        marker.add_argument("--wait-history-thread")
        marker.add_argument("--require-editor-focus", action="store_true")
        options = marker.parse_args(sys.argv[2:])
        if (not math.isfinite(options.wait_history_seconds) or options.wait_history_seconds < 0
                or not math.isfinite(options.wait_history_interval) or options.wait_history_interval <= 0):
            marker.error("History budget must be nonnegative and observation interval positive")
        mark(options.label, wait_history_seconds=options.wait_history_seconds,
             wait_history_interval=options.wait_history_interval,
             wait_history_thread=options.wait_history_thread, image_only=options.image_only,
             require_editor_focus=options.require_editor_focus)
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
    parser.add_argument("--fork-thread", help="Explicit canonical child for owned-fork capture")
    parser.add_argument("--fork-parent", help="Original registered parent of the authorized child")
    parser.add_argument("--fresh-input", help="One new configured-provider input for the owned fork journey")
    parser.add_argument("--actions", type=Path,
                        help="Optional retained script; must match the selected journey, which runs automatically")
    parser.add_argument("--journey", type=PhysicalJourney.decode, default=ScrollJourney,
                        help="Canonical physical journey: " + ", ".join(PhysicalJourney.names()))
    parser.add_argument("--archive-index", type=int, default=0, help="Original retained selector row from the current source namespace")
    parser.add_argument("--peer-thread", help="Actual existing private peer for the warm native roster click")
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
    parser.add_argument("--history-wait-seconds", type=float, default=10,
                        help="Selected peer visible-history observation budget within the same capture deadline")
    parser.add_argument("--history-wait-interval", type=float, default=.1,
                        help="Native diagnostic observation cadence; never repeated process attachment")
    parser.add_argument("--scroll-idle-seconds", type=float, default=4,
                        help="Stationary observation in the shared scroll script; use15 for the original-history delayed-blank reproducer")
    parser.add_argument("--scroll-hold-seconds", type=float, default=4,
                        help="Hold PageUp, PageDown and reverse PageUp for this measured interval")
    parser.add_argument("--review-phase", action="append", default=[], help="Also review this native script marker (up to 8)")
    parser.add_argument("--review-recording", type=Path, help="Encode a retained capture; no UI, ACP or native process launches")
    parser.add_argument("--review-timing", type=ReviewTiming.decode, default=InlineReviewTiming,
                        help="Clip encoding lifetime: " + ", ".join(ReviewTiming.names()))
    parser.add_argument("--profile", action="store_true", help="Sample actual UI and Python workers with installed py-spy")
    parser.add_argument("--capture-state", action="store_true",
                        help="Export loaded DTOs/SVG at before/after and physical phase markers using capture_live --sudo")
    parser.add_argument("--scroll-travel", action="store_true",
                        help="Record native observe travel/relocations for the owned UI (requires --capture-state)")
    parser.add_argument("--profile-rate", type=int, default=25, help="Bounded sampling rate (10-49 Hz)")
    parser.add_argument("--profile-sampling", type=ProfileSampling.decode, default=ConsistentSampling,
                        help="Stack read policy: " + ", ".join(ProfileSampling.names()))
    parser.add_argument("--profile-threads", type=ThreadSampling.decode, default=AllThreadSampling,
                        help="Thread selection: " + ", ".join(ThreadSampling.names()))
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--frame-window-seconds", type=float, default=1,
                        help="Rolling rate window for original native writer receipts")
    parser.add_argument("--live-review-interval", type=float, default=1,
                        help="Expose consecutive finalized video frames during long driver commands; encoding is not visual approval")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--fit-window", action="store_true")
    parser.add_argument("--startup-wait", type=float, default=8)
    parser.add_argument("--max-duration", type=float, default=45,
                        help="Finite observation budget in seconds; never a native turn deadline")
    parser.add_argument("--finalize-seconds", type=float, default=16,
                        help="Reserved within duration for profiler export and owned UI teardown")
    parser.add_argument("--tail-seconds", type=float, default=2)
    parser.add_argument("--slowdown", type=float, default=8)
    parser.add_argument("--review-start", type=float, default=0)
    parser.add_argument("--review-seconds", type=float, default=3)
    parser.add_argument("--review-fps", type=float, default=8)
    parser.add_argument("--review-frames", type=int, default=24)
    parser.add_argument("--sheet-columns", type=int, default=4)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.scroll_travel and not args.capture_state:
        parser.error("Scroll-travel observation requires --capture-state")
    if not math.isfinite(args.scroll_idle_seconds) or not 0 < args.scroll_idle_seconds < args.max_duration:
        parser.error("Scroll idle observation must be positive and shorter than capture duration")
    if not math.isfinite(args.scroll_hold_seconds) or not 0 < args.scroll_hold_seconds < args.max_duration:
        parser.error("Scroll hold must be positive and shorter than capture duration")
    if not (all(0 <= value < args.width for value in
                (args.close_tab_x, args.other_agent_x, args.return_tab_x, args.reopen_agent_x))
            and all(0 <= value < args.height for value in
                    (args.close_tab_y, args.other_agent_y, args.reopen_agent_y))):
        parser.error("Navigation coordinates must be within the isolated recording screen")
    if not math.isfinite(args.navigation_settle_seconds) or not 0 < args.navigation_settle_seconds < args.max_duration:
        parser.error("Navigation observation must be positive and shorter than capture duration")
    if not math.isfinite(args.history_wait_seconds) or not 0 < args.history_wait_seconds < args.max_duration:
        parser.error("Visible history wait must be positive and shorter than capture duration")
    if not math.isfinite(args.history_wait_interval) or not 0 < args.history_wait_interval < args.history_wait_seconds:
        parser.error("Visible history observation interval must be positive and shorter than its budget")
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
    bounds = {"profile_rate": (10, 49), "width": (320, 1920), "height": (240, 1200),
              "slowdown": (1, 16), "review_seconds": (.01, 15),
              "review_frames": (1, 96), "sheet_columns": (1, 8),
              "startup_wait": (0, 119), "tail_seconds": (0, 119), "review_start": (0, 119),
              "finalize_seconds": (ProfileProcess.export_seconds + 6, 30)}
    for name, (low, high) in bounds.items():
        value = getattr(args, name)
        if not math.isfinite(value) or not low <= value <= high:
            parser.error(f"{name} must be finite and between {low} and {high}")
    for name in ("fps", "review_fps", "frame_window_seconds", "live_review_interval"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"{name} must be positive and finite")
    if not math.isfinite(args.max_duration) or args.max_duration < 1:
        parser.error("max_duration must be finite and at least 1")
    if args.width % 2 or args.height % 2:
        parser.error("Capture dimensions must be even for yuv420p")
    if args.startup_wait + args.tail_seconds + args.finalize_seconds + 1 >= args.max_duration:
        parser.error("Duration must leave time for interaction, final screenshot and owned export/teardown")
    if args.review_start >= args.max_duration or args.review_fps > args.fps:
        parser.error("Review must start within capture and sample no faster than capture FPS")
    frames = min(args.review_frames, max(1, math.ceil(args.review_seconds * args.review_fps)))
    pixels = 640 * args.sheet_columns * (640 * args.height / args.width) * math.ceil(frames / args.sheet_columns)
    if pixels > 24_000_000:
        parser.error("Contact sheet exceeds 24 million pixels; reduce review frames")
    print(review_recording(args) if args.review_recording else record(args))


if __name__ == "__main__":
    main()
