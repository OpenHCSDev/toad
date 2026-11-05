"""Hold Toad unfocused while messages arrive, then measure what it paints on return.

The reported behaviour: a window left unfocused for a while shows only its last
message on return, then every missed message arrives in one burst. No existing
scenario can see it, because every input path in the physical harness runs
`xdotool windowfocus` on Toad before typing, so the window is never left blurred.

This holds focus in a second window on the same owned display instead, delivers
messages on the copied bus while Toad is out of focus, then refocuses and counts
the body rows painted immediately afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from agent_comms.active_route import ActiveRoute
from agent_comms.comms import wire
from agent_comms.launch_root import LaunchRoot
from agent_comms.launch_runtime import LaunchRuntime

from tools.physical_ui import OwnedDisplay
from tools.physical_ui_candidate import TerminalApp

BURST = 4
MARKER = "WHILE_UNFOCUSED"


def marker_rows(captured: list[tuple[str, str]]) -> int:
    """How many painted rows carry one of this run's own sent bodies.

    Total row count is the wrong instrument here: the copied session's read basis is a
    MemberActivityDisplayScope digest, whose status row collapses every missed message
    into one "N recent" line (ui_model/status.py:72). Counting the marker counts
    delivered messages instead of digest summaries.

    It counts rows that are painted, so --burst must stay small enough that every
    message fits on screen. A twelve-message burst leaves five markers visible and
    measures the viewport, not the delivery.
    """
    return sum(1 for _, text in captured if MARKER in text)


def window_of(environment: dict[str, str], pid: int) -> str:
    """The X window a process owns on the run's display."""
    found = subprocess.run(
        ("xdotool", "search", "--sync", "--onlyvisible", "--pid", str(pid)),
        env=environment, check=True, capture_output=True, text=True, timeout=20,
    )
    return found.stdout.split()[-1]


def hold_focus_elsewhere(environment: dict[str, str]) -> tuple[subprocess.Popen, str]:
    """A second window that keeps focus so Toad stays unfocused."""
    holder = subprocess.Popen(("st", "-e", "sleep", "300"), env=environment)
    return holder, window_of(environment, holder.pid)


def focus(environment: dict[str, str], window: str) -> None:
    subprocess.run(
        ("xdotool", "windowfocus", "--sync", window),
        env=environment, check=True, timeout=20,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--burst", type=int, default=BURST,
                        help="Messages to send; keep it small enough that every one fits "
                             "on the painted screen, or the count measures the viewport")
    parser.add_argument("--settle-seconds", type=float, default=15.0,
                        help="Wait this long for the transcript to paint a row before sending")
    parser.add_argument("--prime", type=int, default=3,
                        help="Messages sent before the measured burst so the channel view "
                             "has content to settle on; a fresh copy paints nothing until one exists")
    parser.add_argument("--prime-settle-seconds", type=float, default=3.0,
                        help="Let the primed rows paint before the burst is measured")
    parser.add_argument("--runtime", type=Path, required=True, help="The runtime's bin directory")
    parser.add_argument("--thread", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", required=True,
                        help="The private root check-root substituted for {root}")
    parser.add_argument("--channel", default="#comms", help="A channel tab to open")
    parser.add_argument("--from-thread", default="comms-teammate",
                        help="A carried thread that sends to the open tab")
    parser.add_argument("--unfocused-seconds", type=float, default=20.0)
    parser.add_argument("--focused", action="store_true",
                        help="Control run: send while the window keeps focus")
    # The parent CLI owns --comms-root, so the root arrives as --root and the launch
    # is started here. Passing --comms-root in a check-root command makes the parent
    # parse it and resolve the wrong root, which surfaces as a thread-registration
    # error before this script runs.
    arguments = sys.argv[1:]
    args = parser.parse_args(arguments)
    LaunchRoot.startup(["--comms-root", args.root], ActiveRoute.published_launch)

    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    sys.stdout = sys.stderr

    comms = wire()
    target = TerminalApp.prepare_target(comms.root, LaunchRuntime.at_prefix(args.runtime.parent))
    # "toad --comms" is our fork; a bare "toad" is the original application
    # with a different UI and a "Toad" splash.
    # The comms UI is the ACP surface the toad-comms wrapper builds; a bare
    # "toad" is the original application and never shows comms traffic.
    project = str(comms.registry.require(args.thread).worktree)
    base = (str(args.runtime / "toad"), "--comms-root", str(comms.root), "acp",
            f"{args.runtime}/python -m agent_comms.acp", project,
            "--title", "Agent Comms", "--session", args.thread)
    command = base

    measured: dict[str, object] = {}
    with OwnedDisplay(args.output) as display:
        comms.owners.start_many((args.thread,))[0]
        with TerminalApp(command, display, args.output / "comms", target, target.home) as app:
            app.wait("welcome", lambda screen: args.thread in screen.text)
            app.click(args.channel)
            # The bug only shows on a view that has already settled: the run that
            # dropped two messages had 20 rows painted before the first send, and
            # every run that dropped none started on an empty channel view. A fresh
            # copy's channel paints nothing until a message exists, so prime it,
            # then wait for the paint. Send from a settled view or the sample is
            # not the bug.
            for index in range(args.prime):
                comms.messaging.send(args.from_thread, args.channel, f"PRIMED {index:02d}")
                time.sleep(0.25)
            settled_by = time.monotonic() + args.settle_seconds
            while time.monotonic() < settled_by and not list(app.capture().message_rows()):
                time.sleep(0.2)
            time.sleep(args.prime_settle_seconds)
            app.screenshot("shown")
            shown = list(app.capture().message_rows())
            before = len(shown)
            markers_before = marker_rows(shown)

            holder, holder_window = ((None, None) if args.focused
                                     else hold_focus_elsewhere(app.environment))
            try:
                if holder_window is not None:
                    focus(app.environment, holder_window)
                for index in range(args.burst):
                    comms.messaging.send(args.from_thread, args.channel, f"WHILE_UNFOCUSED {index:02d}")
                    time.sleep(0.25)
                time.sleep(args.unfocused_seconds)
                painted = list(app.capture().message_rows())
                painted_while_unfocused = len(painted)
                markers_while_unfocused = marker_rows(painted)
                focus(app.environment, str(app.window))
                time.sleep(0.4)
                returned = list(app.capture().message_rows())
                immediate = len(returned)
                markers_immediately_after_return = marker_rows(returned)
                app.screenshot("returned")
                time.sleep(3.0)
                settled_rows = list(app.capture().message_rows())
                settled = len(settled_rows)
            finally:
                if holder is not None:
                    holder.terminate()
                    holder.wait(timeout=10)

            measured = dict(
                rows_before=before,
                rows_before_zero=before == 0,
                rows_while_unfocused=painted_while_unfocused,
                rows_immediately_after_return=immediate,
                rows_after_settling=settled,
                markers_before=markers_before,
                primed=args.prime,
                markers_while_unfocused=markers_while_unfocused,
                markers_immediately_after_return=markers_immediately_after_return,
                markers_after_settling=marker_rows(settled_rows),
                burst_size=args.burst,
            )
    print(json.dumps(dict(measured, evidence=str(args.output))), file=protocol)


if __name__ == "__main__":
    main()
