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
    "arrival": "a registered scratch sender thread that may post",
    "cli_sync": "TRANSCRIPT: a native transcript file to sync",
    "command": "a conversation where a send is refused, as the live bus has",
    "draft": "waits up to DRAFT_WAIT (240 s) for Core to publish a CLI thread's in-progress draft: a thread mid-turn; times out by design on a scratch bus",
    "goal": "a thread with a goal set by its owner",
    "idle": "runs for DURATION seconds by design; longer than any sweep limit",
    "link": "a drawn link naming a live thread (claude-cloud-pm-run11)",
    "older_bus": "a profile with its theme available (pywal colours): a blank home warns",
    "participants": "a profile with its theme available (pywal colours): a blank home warns",
    "peer_profile": "ADDRESS: a peer's address to open its profile",
    "tab_strip": "unknown: times out on three sidebar threads with the enriched bus too; not looked into",
    "tall_arrival": "sends with a bare `agent-comms send` (no --root), so it posts to the default bus, not the scratch one",
    "tool_detail": "a thread with enough saved history to load an older page, holding tool calls",
}


EXTRA_THREADS = ("claude-a", "opus-personal-model", "personal-model-curation", "scratch-third")
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
        run("register", "--name", name, "--worktree", str(work), "--tags", "comms,scratch", "--execution", "external")
    sender = "scratch-peer"
    for index in range(60):
        run("send", "--from", sender, "--to", "#comms", "--type", "info", "--body", f"channel message {index}")
    run("send", "--from", sender, "--to", "#comms", "--type", "info", "--body", LONG_MESSAGE)
    for index in range(40):
        run("send", "--from", sender, "--to", "scratch-live-pipeline", "--type", "info", "--body", f"direct message {index}")
    for index in range(10):
        run("send", "--from", sender, "--to", "#scratch", "--type", "info", "--body", f"scratch channel message {index}")
    return bus.root


ON_THE_SEEDED_BUS = frozenset({"frame_work"})
"""Drives whose pass mark was measured on the bare seeded bus (`tools/frame_work_baseline.json` counts
Python calls per frame for that bus's rows). On the enriched bus a row mix differs (the tall message
alone moves the row delegate from 112 to 249 calls a frame), the drive refuses by `SystemExit`, and a
`SystemExit` out of a qasync task leaves the loop's executor threads running at exit (SIGABRT)."""


def scenario_names() -> list[str]:
    import qt_drive
    return sorted(member.declared_name for member in qt_drive.Scenario.members_with(qt_drive.Scenario))


def run_one(runtime: Path, name: str, seconds: int, template: Path | None = None) -> tuple[object, str]:
    with tempfile.TemporaryDirectory(prefix="drive-sweep-") as scratch:
        work = Path(scratch)
        bus = ScratchBus(runtime, work)
        bus.home.mkdir(parents=True)
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
        }
        try:
            done = subprocess.run(
                [str(runtime / "bin" / "python"), str(HERE / "qt_drive.py"), name, str(out), "--comms-root", str(bus.root)],
                env=env, cwd=ROOT, capture_output=True, text=True, timeout=seconds)
        except subprocess.TimeoutExpired:
            return "TIMEOUT", ""
        text = done.stdout + done.stderr
        if os.environ.get("DRIVE_SWEEP_OUT"):
            Path(os.environ["DRIVE_SWEEP_OUT"]).mkdir(parents=True, exist_ok=True)
            (Path(os.environ["DRIVE_SWEEP_OUT"]) / f"{name}.txt").write_text(text)
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
