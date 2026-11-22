"""The Qt agent tab, on a scratch bus: the tests' scripted ACP peer runs a full turn (a reply, a
thought, a tool call, a permission question, terminal output) and each arrives as a live row.

    tools/agent_session_check.py RUNTIME

Seeds a throwaway bus root (the shipped-app check's `ScratchBus`), runs `qt_drive agent_session`
over it from this checkout on RUNTIME's interpreter and exits non-zero, with the drive's output,
when it fails. No model and no live bus: the peer is `tests/support/agents.py`'s.

A Qt agent tab failed at mount for a long while (`UnboundTranscript.mounted` asked the view for
a Textual widget's method), because no check opened one: the shipped-app run covers every view
kind but the agent session, which needs this scripted peer from the source tree.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE / "android"))
from shipped_run import ScratchBus  # noqa: E402


def main(arguments: list[str]) -> int:
    if len(arguments) != 2:
        print(__doc__)
        return 2
    runtime = Path(arguments[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="agent-session-check-") as scratch:
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
        }
        try:
            done = subprocess.run(
                [str(runtime / "bin" / "python"), str(HERE / "qt_drive.py"), "agent_session", str(out),
                 "--comms-root", str(bus.root)],
                env=env, cwd=ROOT, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            print("error: the Qt agent session drive did not finish in 300 s", file=sys.stderr)
            return 1
    shown = "\n".join(line for line in done.stdout.splitlines() if "propagateSizeHints" not in line)
    if done.returncode != 0 or "3-turn-over" not in shown or "busy=False" not in shown:
        print(f"error: the Qt agent session failed on a scratch bus (exit {done.returncode})", file=sys.stderr)
        print(shown[-3000:], file=sys.stderr)
        print("\n".join(done.stderr.splitlines()[-25:]), file=sys.stderr)
        return 1
    print("the Qt agent session ran a full scripted turn on a scratch bus")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
