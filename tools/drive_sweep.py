"""Every qt_drive scenario, each on its own fresh scratch bus: which ones fail now.

    tools/drive_sweep.py RUNTIME [SCENARIO ...]        (about 25 minutes for all)

The drives are the proof of what Qt draws and does, and no merge check runs more than a few of
them, so they rot: a rename leaves one reading an attribute that is gone (`settings_read`), and a
whole view kind can be broken with none noticing (a Qt agent tab raised at mount until
`tools/agent_session_check.py` opened one). This runs them all against the seeded scratch bus the
shipped-app check uses and reports each one's exit status and last error.

A generic scratch bus has two messages, one channel and two threads, so some drives cannot pass
on it: they need a named live thread, a history taller than the window, or an environment value.
`NEEDS_MORE_THAN_THE_SCRATCH_BUS` lists them with what each needs. The sweep exits non-zero for a
scenario that fails and is not listed, and for a listed one that now passes (the entry is stale).
"""
from __future__ import annotations

import os
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
    "delivery_preview": "unconfirmed: a thread with no status line has no height in its info bar, so the first held count moves the history by one line",
    "draft": "times out at 100 s on a scratch bus (waits on a draft a live peer holds); not looked into",
    "escape": "#comms taller than the window (a tail to scroll off)",
    "goal": "a live thread named claude-a",
    "hold": "message rows under the held points: a history of several messages",
    "idle": "runs for DURATION seconds by design; longer than any sweep limit",
    "jump_back": "a history taller than the window",
    "link": "a live thread named opus-personal-model",
    "menu_float": "message rows to open a message menu on",
    "menu_parity": "a channel named #scratch",
    "older_bus": "a profile with its theme available (pywal colours): a blank home warns",
    "peer_profile": "ADDRESS: a peer's address to open its profile",
    "participants": "a profile with its theme available (pywal colours): a blank home warns",
    "slide": "a saved sidebar placement; a blank profile opens at its default extent",
    "sticky": "a message taller than the window",
    "tab_strip": "three threads in the sidebar",
    "tall_arrival": "a history taller than the window",
    "tool_detail": "a live thread named claude-a",
    "transcript": "a live thread named personal-model-curation",
}


def scenario_names() -> list[str]:
    import qt_drive
    return sorted(member.declared_name for member in qt_drive.Scenario.members_with(qt_drive.Scenario))


def run_one(runtime: Path, name: str, seconds: int) -> tuple[object, str]:
    with tempfile.TemporaryDirectory(prefix="drive-sweep-") as scratch:
        work = Path(scratch)
        bus = ScratchBus(runtime, work)
        bus.home.mkdir(parents=True)
        bus.seed()
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
    for name in chosen:
        began = time.time()
        code, last = run_one(runtime, name, int(os.environ.get("EACH", "150")))
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
