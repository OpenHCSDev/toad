#!/usr/bin/env python3
"""Toad's installed-runtime check in an owned, source-checked physical run.

    <runtime>/bin/python -I tools/acceptance.py --runtime RUNTIME_BIN --thread NAME --output DIR

Core supplies a rehearsal root and thread. A fresh frontend home does NOT restore
source-bound saved Toad tabs. Plain st and the real ACP editor share TerminalApp's
startup-owned source/runtime/persistence admission. SHOWN, SEEN and the final
JSON retain Core's existing protocol; failed/UNKNOWN fresh input is never replayed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import time

from agent_comms.active_route import ActiveRoute
from agent_comms.comms import wire
from agent_comms.launch_root import LaunchRoot
from agent_comms.launch_runtime import LaunchRuntime
from agent_comms.ui_model.message_category import InboundCategory, all_categories
from toad.widgets.side_bar import BackTabButton

# Isolated Python omits the script directory; this tool owns its sibling imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from physical_ui import OwnedDisplay, TerminalApp


def any_channel(screen):
    return "#any · all comms" in screen.text and "IRC / Markdown" in screen.text


def check_typed_reply(app: TerminalApp, thread: str, output: Path) -> None:
    """A physical submit finishes in the native journal and survives tab return."""
    comms = wire()
    selected = comms.registry.require(thread)
    session = selected.runtime.history_source(comms.root, selected.incarnation)
    token = "TYPED_REPLY_" + str(time.time_ns())
    attempt = {"status": "UNKNOWN", "replay": False, "thread": thread, "token": token}
    marker = output / "typed-input.json"
    app.click_cell(app.columns // 2, app.rows - 4)
    app.type_text("Reply with " + token + ". Do not use tools.")
    marker.write_text(json.dumps(attempt))
    started = time.monotonic()
    app.keys("Return")

    def replies():
        return tuple(entry for entry in session.tail(max_bytes=1024 * 1024)
                     if entry.assistant_message and entry.final_reply
                     and entry.message.text.strip() == token)

    def visible(text):
        return any(cell.strip("▌ ") == token for _, cell in text.message_rows())

    app.wait("typed-reply", lambda text: bool(replies())
             and not comms.registry.require(thread).executing and visible(text), seconds=180)
    reply, = replies()
    attempt.update(status="COMPLETED", reply_id=reply.require_entry_id(),
                   reply_seconds=time.monotonic() - started)
    marker.write_text(json.dumps(attempt))
    app.screenshot("typed-reply")
    app.click("#any")
    app.wait("typed-away", any_channel)
    app.click(thread)
    app.wait("typed-return", lambda screen: visible(screen) and "User messages" in screen.text)
    app.screenshot("typed-return")


def check_answer(app: TerminalApp, thread: str, answer: str) -> None:
    expected = "".join(answer.split())

    def visible(text):
        return expected in text.messages()

    app.wait("answer", visible)
    app.screenshot("answer")
    app.click("#any")
    app.wait("answer-any", lambda text: any_channel(text) and visible(text))
    app.screenshot("answer-any")
    initial = app.reader_place("any-initial")
    app.click_cell(app.columns // 2, app.rows - 4)
    app.keys("Page_Up", "Page_Up", "Page_Up")
    app.wait("any-page-up", lambda screen: bool(screen.reader_position())
             and screen.reader_position() != initial)
    app.toggle_group("#any")
    app.click("#comms")
    app.wait("comms", lambda screen: "#comms" in "\n".join(screen.text.splitlines()[:3]) and "IRC / Markdown" in screen.text)
    app.toggle_group("#any")
    app.click(thread)
    app.wait("answer-return", lambda screen: visible(screen) and "User messages" in screen.text)
    app.screenshot("answer-return")


def check_filtered_return(app: TerminalApp, thread: str) -> None:
    for category in all_categories() - {InboundCategory}:
        app.hide_category(category.label)
    expected = app.reader_place("filtered-before")
    app.screenshot("filtered-before")
    app.click("#any")
    app.wait("filtered-away", any_channel)
    app.click(BackTabButton.label)
    app.wait("filtered-return", lambda screen: screen.reader_position() == expected)
    app.click("#any")
    app.wait("filtered-click-away", any_channel)
    app.click(thread)
    app.wait("filtered-click-return", lambda screen: screen.reader_position() == expected)
    app.screenshot("filtered-click-return")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime", type=Path, required=True, help="The runtime's bin directory")
    parser.add_argument("--thread", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = sys.argv[1:]
    LaunchRoot.startup(arguments, ActiveRoute.published_launch)
    args = parser.parse_args(arguments)
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    sys.stdout = sys.stderr
    comms = wire()
    target = TerminalApp.prepare_target(comms.root, LaunchRuntime.at_prefix(args.runtime.parent))
    with OwnedDisplay(args.output) as display:
        command = (str(args.runtime / "toad"),)
        plain = TerminalApp((*command, str(target.home)), display, args.output / "plain", target, target.home)
        with display.recording(args.output / "journey.mp4", plain.environment):
            with plain as app:
                app.wait("store", lambda screen: "Toad" in screen.text or "agent" in screen.text.lower())
                app.screenshot("store")
            comms.owners.start_many((args.thread,))[0]
            command = (*command, "acp", shlex.quote(str(args.runtime / "agent-comms-acp")),
                       str(comms.registry.require(args.thread).worktree),
                       "--session", args.thread, "--title", "Agent Comms")
            with TerminalApp(command, display, args.output / "comms", target, target.home) as app:
                app.wait("welcome", lambda screen: args.thread in screen.text)
                app.click(args.thread)
                app.show_thread(args.thread)
                app.screenshot("shown")
                check_typed_reply(app, args.thread, args.output)
                print("SHOWN", file=protocol)
                answer = json.loads(sys.stdin.readline())
                check_answer(app, args.thread, answer)
                check_filtered_return(app, args.thread)
                print("SEEN", file=protocol)
    print(json.dumps(dict(plain="passed", shown="passed", answer="passed", channels="passed",
                          filtered_return="passed", evidence=str(args.output))), file=protocol)


if __name__ == "__main__":
    main()
