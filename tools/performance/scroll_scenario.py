#!/usr/bin/env python3
"""Record real stopped-history scrolling through the common private-run owner.

Run with the installed SOURCE runtime's Python. --runtime chooses only the
frontend/copy runtime; it never opens the original Comms through that candidate.
No provider input, live-root fork or automatic metadata-capture approval occurs.
This retained-history scenario is NOT comparable to the old active-response
shell benchmark without stating their different source/traffic scopes.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_comms.active_route import ActiveRoute
from agent_comms.comms import wire
from agent_comms.launch_root import LaunchRoot
from agent_comms.launch_runtime import LaunchRuntime
from physical_ui import TerminalApp
from physical_ui_remote import ObservedResult, PhysicalOperation
from textual.geometry import Size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--history-thread", action="append", default=[])
    parser.add_argument("--runtime", type=Path, default=LaunchRuntime.installed().prefix)
    parser.add_argument("--output", type=Path, required=True, help="Fresh owned agent-scratch directory")
    parser.add_argument("--columns", type=int, default=140)
    parser.add_argument("--rows", type=int, default=40)
    arguments = sys.argv[1:]
    LaunchRoot.startup(arguments, ActiveRoute.published_launch)
    args = parser.parse_args(arguments)
    if LaunchRuntime.running().prefix != LaunchRuntime.installed().prefix:
        parser.error("History must be copied by the installed source runtime, not the candidate")
    if args.columns <= 0 or args.rows <= 0:
        parser.error("A terminal needs positive columns/rows")
    threads = tuple(dict.fromkeys((args.thread, *args.history_thread)))
    with TerminalApp.copied(
        wire(), threads, LaunchRuntime.at_prefix(args.runtime), args.output,
        thread=args.thread, size=Size(args.columns, args.rows),
    ) as app:
        app.wait("history", lambda screen: bool(screen.reader_position()))
        PhysicalOperation.publish(args.output / "admitted.json", ObservedResult(app.observe()))
        app.screenshot("startup")
        app.click_cell(app.columns // 2, app.rows // 3)
        app.input("key", "--clearmodifiers", "--repeat", "20", "--delay", "75", "Page_Up")
        app.screenshot("page-up")
        app.input("key", "--clearmodifiers", "--repeat", "8", "--delay", "75", "Page_Down")
        app.screenshot("reversal")
        app.keys("End")
        app.screenshot("end-immediate")
        app.input("click", "--repeat", "12", "--delay", "60", "4")
        app.screenshot("wheel-up")
        app.keys("End")
        app.screenshot("end-return")
    print(args.output)


if __name__ == "__main__":
    main()
