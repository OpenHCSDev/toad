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

BURST = 12


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
    parser.add_argument("--runtime", type=Path, required=True, help="The runtime's bin directory")
    parser.add_argument("--thread", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", required=True,
                        help="The private root check-root substituted for {root}")
    parser.add_argument("--channel", default="#comms")
    parser.add_argument("--unfocused-seconds", type=float, default=20.0)
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
    base = (str(args.runtime / "toad"), "--comms-root", str(comms.root))  # toad [OPTIONS] COMMAND
    command = (*base, "acp", shlex.quote(str(args.runtime / "agent-comms-acp")),
               str(comms.registry.require(args.thread).worktree),
               "--session", args.thread, "--title", "Agent Comms")

    measured: dict[str, object] = {}
    with OwnedDisplay(args.output) as display:
        comms.owners.start_many((args.thread,))[0]
        with TerminalApp(command, display, args.output / "comms", target, target.home) as app:
            app.wait("welcome", lambda screen: args.thread in screen.text)
            app.click(args.thread)
            app.screenshot("shown")
            before = len(list(app.capture().message_rows()))

            holder, holder_window = hold_focus_elsewhere(app.environment)
            try:
                focus(app.environment, holder_window)
                for index in range(BURST):
                    comms.messaging.send(args.thread, args.channel, f"WHILE_UNFOCUSED {index:02d}")
                    time.sleep(0.25)
                time.sleep(args.unfocused_seconds)
                painted_while_unfocused = len(list(app.capture().message_rows()))
                focus(app.environment, str(app.window))
                time.sleep(0.4)
                immediate = len(list(app.capture().message_rows()))
                app.screenshot("returned")
                time.sleep(3.0)
                settled = len(list(app.capture().message_rows()))
            finally:
                holder.terminate()
                holder.wait(timeout=10)

            measured = dict(
                rows_before=before,
                rows_while_unfocused=painted_while_unfocused,
                rows_immediately_after_return=immediate,
                rows_after_settling=settled,
                burst_visible_in_window=any(
                    "WHILE_UNFOCUSED" in text for _, text in app.capture().message_rows()
                ),
            )
    print(json.dumps(dict(measured, evidence=str(args.output))), file=protocol)


if __name__ == "__main__":
    main()
