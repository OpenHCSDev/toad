"""Every qt_drive scenario, each on its own fresh scratch bus: which ones fail now.

    tools/drive_sweep.py RUNTIME [SCENARIO ...]        (about 25 minutes for all)

The drives are the proof of what Qt draws and does, and no merge check runs more than a few of
them, so they rot: a rename leaves one reading an attribute that is gone (`settings_read`), and a
whole view kind can be broken with none noticing (a Qt agent tab raised at mount until
`tools/agent_session_check.py` opened one). This runs them all against the seeded scratch bus the
shipped-app check uses and reports each one's exit status and last error.

The bus each drive runs on is the seeded scratch bus enriched with what long-history drives need
(`enriched_template`: sixty messages, a tall one, `#scratch`, the named threads; `ENRICHED=0` uses the bare
seeded bus). Some drives still cannot pass on it: they need a live thread's own state or an environment
value.
`NEEDS_MORE_THAN_THE_SCRATCH_BUS` lists them with what each needs. The sweep exits non-zero for a
scenario that fails and is not listed, and for a listed one that now passes (the entry is stale).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE / "android"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from shipped_run import ScratchBus  # noqa: E402

NEEDS_MORE_THAN_THE_SCRATCH_BUS: dict[str, str] = {
    "cli_sync": "TRANSCRIPT: a native transcript file to sync",
    "draft": "waits up to DRAFT_WAIT (240 s) for Core to publish a CLI thread's in-progress draft: a thread mid-turn; times out by design on a scratch bus",
    "goal": "a thread with a goal set by its owner",
    "idle": "runs for DURATION seconds by design; longer than any sweep limit",
    "peer_profile": "ADDRESS: a peer's address to open its profile",
    "tool_detail": "a thread with enough saved history to load an older page, holding tool calls",
}


EXTRA_THREADS = ("claude-a", "opus-personal-model", "personal-model-curation", "scratch-third",
                 "claude-cloud-pm-run11")
"""Threads the drives name that a bare scratch bus lacks, registered with the channels' tags."""
LONG_MESSAGE = "\n".join(f"line {number} of a message taller than any window: " + "word " * 12 for number in range(1, 91))


def enriched_template(runtime: Path, parent: Path) -> Path:
    """A scratch bus root with what long-history drives need: the named threads, a channel
    `#scratch`, sixty short messages in `#comms`, forty in a direct message, and one tall one.
    Built once; each scenario then runs on its own copy."""
    work = parent / "template"
    bus = ScratchBus(runtime, work)
    bus.home.mkdir(parents=True)
    bus.seed()
    cli, env = runtime / "bin" / "agent-comms", os.environ | {"HOME": str(bus.home)}

    def run(*words: str) -> None:
        done = subprocess.run([str(cli), "--root", str(bus.root), *words], cwd=work, env=env,
                              capture_output=True, text=True, timeout=120)
        if done.returncode or ('"id"' not in done.stdout and words[0] == "send"):
            raise RuntimeError(f"{' '.join(words)[:80]} failed: {done.stdout[-300:]}{done.stderr[-300:]}")

    for name in EXTRA_THREADS:
        # Each is a live external thread (this process is alive for the whole sweep): a link to a
        # recorded one opens nothing in Qt (`select_historical`).
        run("register", "--name", name, "--worktree", str(work), "--tags", "comms,scratch",
            "--execution", "external", "--pid", str(os.getpid()))
    sender = "scratch-peer"
    for index in range(60):
        run("send", "--from", sender, "--to", "#comms", "--type", "info", "--body", f"channel message {index}")
    run("send", "--from", sender, "--to", "#comms", "--type", "info", "--body", LONG_MESSAGE)
    for index in range(40):
        run("send", "--from", sender, "--to", "scratch-live-pipeline", "--type", "info", "--body", f"direct message {index}")
    for index in range(10):
        run("send", "--from", sender, "--to", "#scratch", "--type", "info", "--body", f"scratch channel message {index}")
    # A message naming a thread by its name draws it as a link (the `link` drive taps it).
    run("send", "--from", sender, "--to", "opus-personal-model", "--type", "info",
        "--body", "the run is in claude-cloud-pm-run11, see its thread")
    return bus.root


ON_THE_SEEDED_BUS = frozenset({"frame_work"})
"""Drives whose pass mark was measured on the bare seeded bus (`tools/frame_work_baseline.json` counts
Python calls per frame for that bus's rows). On the enriched bus a row mix differs (the tall message
alone moves the row delegate from 112 to 249 calls a frame), the drive refuses by `SystemExit`, and a
`SystemExit` out of a qasync task leaves the loop's executor threads running at exit (SIGABRT)."""


def write_wal_palette(home: Path) -> None:
    """pywal's `colors.json` in a scratch home. Toad's default theme is `wal`, which a blank home
    has no file for: the app posts a "Theme 'wal' is not available" warning no real home shows,
    and the drives that expect no warning (older_bus, participants) fail on it."""
    import json

    greys = [f"#{level:02x}{level:02x}{level:02x}" for level in range(0x10, 0x100, 0x10)]
    palette = {f"color{index}": greys[index % len(greys)] for index in range(16)}
    cache = home / ".cache" / "wal"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "colors.json").write_text(json.dumps({
        "wallpaper": "", "alpha": "100",
        "special": {"background": "#101010", "foreground": "#e0e0e0", "cursor": "#e0e0e0"},
        "colors": palette}))


ON_A_HOME_WITHOUT_PYWAL = frozenset({"shipped"})
"""Drives that assert the start theme is one Qt does not offer: with a pywal file, `wal` is offered."""


def scenario_names() -> list[str]:
    import qt_drive
    return sorted(member.declared_name for member in qt_drive.Scenario.members_with(qt_drive.Scenario))


def keep_output(name: str, text: str) -> None:
    """A drive's whole output, under DRIVE_SWEEP_OUT when that names a directory."""
    where = os.environ.get("DRIVE_SWEEP_OUT")
    if where:
        Path(where).mkdir(parents=True, exist_ok=True)
        (Path(where) / f"{name}.txt").write_text(text)


def run_one(runtime: Path, name: str, seconds: int, template: Path | None = None) -> tuple[object, str]:
    with tempfile.TemporaryDirectory(prefix="drive-sweep-") as scratch:
        work = Path(scratch)
        bus = ScratchBus(runtime, work)
        bus.home.mkdir(parents=True)
        if name not in ON_A_HOME_WITHOUT_PYWAL:
            write_wal_palette(bus.home)
        if template is None or name in ON_THE_SEEDED_BUS:
            bus.seed()
        else:
            shutil.copytree(template, bus.root)
        out = work / "out"
        out.mkdir()
        env = {key: value for key, value in os.environ.items() if key != "XDG_CONFIG_HOME"} | {
            "HOME": str(bus.home),
            "XDG_STATE_HOME": str(work / "state"),
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONPATH": os.pathsep.join(str(ROOT / part) for part in ("src", "tools", "tests")),
            "TARGET": "scratch-live-pipeline",
            "PEER": "scratch-peer",
            "COMMS_ROOT": str(bus.root),
        }
        # A drive past its time is stopped with SIGABRT under the fault handler, so what it was
        # stuck in is every thread's stack in its output; `timeout` answers 124 for it.
        done = subprocess.run(
            ["timeout", "-s", "ABRT", str(seconds), str(runtime / "bin" / "python"), str(HERE / "qt_drive.py"),
             name, str(out), "--comms-root", str(bus.root)],
            env=env | {"PYTHONFAULTHANDLER": "1"}, cwd=ROOT, capture_output=True, text=True, timeout=seconds + 60)
        if done.returncode == 124:
            keep_output(name, done.stdout + done.stderr)
            return "TIMEOUT", ""
        text = done.stdout + done.stderr
        keep_output(name, text)
    lines = [line for line in text.splitlines()
             if line and not line.startswith((" ", "Traceback", "RuntimeWarning", "qt.")) and "propagateSizeHints" not in line
             and "handle = None" not in line]
    last = next((line for line in reversed(lines) if "Error" in line or "error" in line or "fail" in line.lower()),
                lines[-1] if lines else "")
    return done.returncode, last[:160]


def main(arguments: list[str]) -> int:
    if len(arguments) < 2:
        print(__doc__)
        return 2
    runtime = Path(arguments[1]).resolve()
    chosen = arguments[2:] or scenario_names()
    unexpected, stale = [], []
    keep = tempfile.TemporaryDirectory(prefix="drive-sweep-template-")
    template = None if os.environ.get("ENRICHED") == "0" else enriched_template(runtime, Path(keep.name))
    for name in chosen:
        began = time.time()
        code, last = run_one(runtime, name, int(os.environ.get("EACH", "150")), template)
        passed = code == 0
        listed = name in NEEDS_MORE_THAN_THE_SCRATCH_BUS
        verdict = "ok" if passed and not listed else "FAILS (listed)" if listed and not passed else "PASSES NOW, drop from the list" if passed else "FAILS"
        print(f"{name:20} {str(code):7} {time.time() - began:4.0f}s  {verdict:30} {last}", flush=True)
        if not passed and not listed:
            unexpected.append(name)
        if passed and listed:
            stale.append(name)
    if unexpected:
        print(f"\nfailing and not listed: {', '.join(unexpected)}")
    if stale:
        print(f"\nlisted and passing: {', '.join(stale)}")
    return 1 if unexpected or stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
