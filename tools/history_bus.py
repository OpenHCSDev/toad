"""A scratch bus whose #comms has a long history, served as the phone reaches a bus, for the
history drives (qt_drive's `history_scroll_back`, `tools/tui_scroll_back.py`) when the live bus
is not the thing measured, or is not up.

    RUNTIME/bin/python tools/history_bus.py RUNTIME WORK [MESSAGES]

Seeds WORK/root with MESSAGES (default 400) channel messages of mixed length, Markdown, code and
file paths (the history row's formatting resolves those) from two peers, serves it over loopback
TLS with a UI grant (`tools/android/shipped_run.ScratchBus`), writes WORK/trust.pem (its
certificate with the system's CAs, for SSL_CERT_FILE) and prints the UI profile's path. It
serves until stopped.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "android"))
from shipped_run import CHANNEL, PEER, THREAD, ScratchBus, run  # noqa: E402

BODIES = (
    "short note {n}",
    "A longer message {n}, the kind a teammate writes when explaining what changed: the pager "
    "reads older pages as the reader nears the top, and each page's rows are measured before they "
    "are shown, so a slow measurement is a slow page.",
    "Changed `src/toad/qt/history.py` and src/toad/motion.py for {n}; see README.md and "
    "tools/qt_drive.py:2400 for the drive.",
    "## Status {n}\n\n- the first point\n- the second point, with **bold** and `code`\n- a third\n\n"
    "Then a closing paragraph.",
    "```python\ndef page_{n}(rows):\n    return [row for row in rows if row.shown]\n```\nThat's the shape.",
)


def seed(bus: ScratchBus, messages: int) -> None:
    bus.seed()
    cli = bus.runtime / "bin" / "agent-comms"
    run(cli, "--root", bus.root, "register", "--name", "scratch-second", "--worktree", bus.work,
        "--tags", CHANNEL, "--execution", "external", cwd=bus.work)
    from agent_comms.comms import Comms
    from agent_comms.installer.active_route import resolve_comms_route

    comms = Comms(resolve_comms_route(bus.root))
    senders = (PEER, "scratch-second", THREAD)
    for n in range(messages):
        comms.messaging.send(senders[n % len(senders)], f"#{CHANNEL}", BODIES[n % len(BODIES)].format(n=n))


def main(runtime: Path, work: Path, messages: int) -> None:
    work.mkdir(parents=True, exist_ok=True)
    work.chmod(0o700)  # the UI profile's grant lives in an owner-only directory
    bus = ScratchBus(runtime, work)
    seed(bus, messages)
    profile = bus.serve()
    import certifi

    (work / "trust.pem").write_text(Path(certifi.where()).read_text() + (work / "cert.pem").read_text())
    print(profile, flush=True)
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    try:
        while not stop["now"]:
            signal.pause()
    finally:
        bus.stop()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 400)
