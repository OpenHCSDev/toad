#!/usr/bin/env python3
"""Toad's half of an installed runtime's check: what a person sees in a terminal.

    <runtime>/bin/python -I tools/acceptance.py --runtime RUNTIME_BIN --thread NAME --output DIR

Core's installer runs this with the runtime under check, in a home whose route selects
a rehearsal copy of the bus, on a thread it made there. Everything runs in plain st on
an Xvfb display this tool owns. Plain ``toad`` must start; its ACP entrypoint must
show the thread ready. This tool types one fresh request into that open tab, checks
its final native reply and returns to the tab. It then says SHOWN. Core sends the thread a DM and,
once the thread has answered on the bus, writes the answer here as one JSON string; it
must appear in the thread, in #any and again on return to the thread, and the reader
position must survive leaving and returning with only that DM's category shown. The
tool then says SEEN. The last line printed is the result.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from agent_comms.comms import wire
from agent_comms.ui_model.message_category import InboundCategory, all_categories
from rich.cells import cell_len

from toad.widgets.side_bar import BackTabButton

# Isolated Python omits the script directory; this tool owns its sibling imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from performance.capture_live import XvfbDisplay


def run(*args: str | Path) -> str:
    print("+ " + " ".join(map(str, args)), file=sys.stderr, flush=True)
    return subprocess.check_output(list(map(str, args)), text=True, timeout=10).strip()


class OwnedDisplay(XvfbDisplay):
    """The isolated display this check creates and removes."""

    def __init__(self, output: Path):
        output.mkdir(parents=True, exist_ok=True)
        self.log = (output / "xvfb.log").open("w")
        self.server = subprocess.Popen(
            ["Xvfb", "-displayfd", "1", "-screen", "0", "1600x1000x24", "-nolisten", "tcp"],
            stdout=subprocess.PIPE, stderr=self.log)
        try:
            super().__init__(":" + self.server.stdout.readline().decode().strip())
        except BaseException:
            self.close_server()
            raise

    def close_server(self) -> None:
        self.server.terminate()
        self.server.wait(timeout=5)
        self.log.close()

    def __exit__(self, *exception):
        try:
            return super().__exit__(*exception)
        finally:
            self.close_server()


class TerminalApp:
    """Own one isolated st window, its screen and physical X input."""

    columns, rows = 140, 40

    def __init__(self, command, display, output, environment, cwd):
        self.command, self.display, self.output = command, display, output
        self.environment = dict(environment, DISPLAY=display.name)
        self.cwd = cwd

    def __enter__(self):
        import psutil
        self.output.mkdir(parents=True, exist_ok=True)
        self.dump = self.output / "st-screen.txt"
        self.log = (self.output / "st.log").open("w")
        self.terminal = subprocess.Popen(
            ["st", "-f", "DejaVu Sans Mono:pixelsize=16", "-g", f"{self.columns}x{self.rows}",
             "-o", str(self.dump), "-e", "env", f"HOME={self.environment['HOME']}",
             *map(str, self.command)],
            cwd=self.cwd, env=self.environment, stdout=self.log, stderr=self.log)
        self.owner = psutil.Process(self.terminal.pid)
        self.created = self.owner.create_time()
        try:
            self.window = int(subprocess.check_output(
                ["xdotool", "search", "--sync", "--onlyvisible", "--pid", str(self.terminal.pid)],
                env=self.environment, text=True, timeout=10).splitlines()[0])
            self.read_grid()
            # -o enables st's raw printer too; Ctrl+Print leaves only explicit dumps.
            self.keys("ctrl+Print")
            self.wait("terminal", lambda text: bool(text.strip()))
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def capture(self):
        """Read st's own print-screen output; screenshots record the visible window."""
        offset = self.dump.stat().st_size
        self.keys("shift+Print")
        deadline = time.monotonic() + 2
        while True:
            with self.dump.open("rb") as stream:
                stream.seek(offset)
                data = stream.read()
            if data.count(b"\n") >= self.rows:
                return data.decode("utf-8")
            if self.terminal.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("st did not finish its screen dump")
            time.sleep(.02)

    def message_rows(self, text):
        """Each screen row's middle pane, decoded through the sidebar boundaries.

        st's dump drops trailing blanks; padding restores the full row, so a pane's
        last columns are its gutter.
        """
        for row, line in enumerate(text.splitlines()):
            panes = (line + " " * (self.columns - cell_len(line))).split("│")
            if len(panes) >= 2:
                yield row, "│".join(panes[1:-1] if len(panes) >= 3 else panes[1:])

    def messages(self, text):
        """Each visible message's body, its wrapped rows joined without whitespace.

        A body runs from its ``───`` header to its ``▶`` status row; the last two
        columns are the scrollbar gutter.
        """
        message = None
        for _, cell in self.message_rows(text):
            body = cell[:-2].strip()
            content = body.lstrip("▌").strip()
            if not body.startswith("▌") or content.startswith(("─", "▶")):
                if message:
                    yield message
                message = "" if content.startswith("─") else None
            elif message is not None:
                message += "".join(content.split())
        if message:
            yield message

    def reader_position(self, text):
        """First visible message and its screen row, excluding the scrollbar gutter."""
        for row, cell in self.message_rows(text):
            body = cell[:-2]
            if body.startswith("▌") and body.strip("▌ "):
                return row, body
        return ()

    def reader_place(self, name):
        """Observe a settled message viewport after one navigation action."""
        previous = ()

        def settled(text):
            nonlocal previous
            rows = self.reader_position(text)
            # This connection banner occupies a transcript row until it closes.
            same = "Agent Comms connected" not in text and bool(rows) and rows == previous
            previous = rows
            return same

        return self.reader_position(self.wait(name, settled))

    def screenshot(self, name):
        path = self.output / f"{name}.png"
        run("import", "-display", self.display.name, "-window", str(self.window), path)
        return path

    def wait(self, name, predicate, seconds=60):
        deadline = time.monotonic() + seconds
        previous = ""
        changes = self.output / f"{name}-changes.txt"
        while True:
            text = self.capture()
            if text != previous:
                with changes.open("a") as log:
                    log.write(f"\n--- {time.monotonic()} ---\n{text}")
                previous = text
            if predicate(text):
                (self.output / f"{name}.txt").write_text(text)
                return text
            if self.terminal.poll() is not None or time.monotonic() >= deadline:
                (self.output / f"{name}-failed.txt").write_text(text)
                self.screenshot(f"{name}-failed")
                raise RuntimeError(f"Terminal probe {name} failed; see {self.output}")
            time.sleep(.2)

    def keys(self, *keys):
        XvfbDisplay.input(self.owner, self.created, self.window, "key", "--clearmodifiers", *keys)

    def type_text(self, text):
        XvfbDisplay.input(self.owner, self.created, self.window,
                          "type", "--clearmodifiers", "--delay", "1", text)

    def show_thread(self, thread):
        self.wait("ready", lambda text: thread in text
                  and "▶ Session details · Ready" in "\n".join(text.splitlines()[-8:]))
        # The thread sidebar starts collapsed; expand its visible right gutter.
        self.click_cell(self.columns - 1, self.rows // 2)
        return self.wait("shown", lambda text: "User messages" in text and all(
            "Indexing" not in line.split("│", 1)[0] for line in text.splitlines()))

    def click(self, label):
        text = self.wait("find-" + label.replace("/", "-"), lambda text: any(
            label in line.split("│", 1)[0] for line in text.splitlines()))
        row, line = next((row, line) for row, line in enumerate(text.splitlines())
                         if label in line.split("│", 1)[0])
        self.click_cell(cell_len(line[:line.index(label)]) + cell_len(label) // 2, row)

    def toggle_group(self, label):
        """Click this sidebar group's disclosure, collapsing or expanding its members."""
        def header(line):
            return line.split("│", 1)[0].lstrip().startswith(("▾ " + label, "▸ " + label))
        text = self.wait("find-group-" + label, lambda text: any(map(header, text.splitlines())))
        row, line = next((row, line) for row, line in enumerate(text.splitlines()) if header(line))
        glyph = min(index for index in (line.find("▾"), line.find("▸")) if index >= 0)
        self.click_cell(cell_len(line[:glyph]), row)

    def hide_category(self, label):
        """Click this checkbox in the right sidebar, never matching message text."""
        def control(text):
            return next(((row, line) for row, line in enumerate(text.splitlines())
                         if "│" in line and label in line.rsplit("│", 1)[-1]), None)
        text = self.wait("find-filter-" + label.replace("/", "-"), lambda text: control(text) is not None)
        row, line = control(text)
        prefix, panel = line.rsplit("│", 1)
        self.click_cell(cell_len(prefix + "│" + panel[:panel.index("▐")]) + 1, row)

    def read_grid(self):
        """st declares one cell plus its padding as the X minimum window size."""
        geometry = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", str(self.window)],
            env=self.environment, text=True)
        size = dict(line.split("=", 1) for line in geometry.splitlines() if "=" in line)
        hints = subprocess.check_output(
            ["xprop", "-display", self.display.name, "-id", str(self.window), "WM_NORMAL_HINTS"],
            env=self.environment, text=True)
        declared = {name: (int(width), int(height)) for name, width, height in re.findall(
            r"program specified (minimum size|base size): (\d+) by (\d+)", hints)}
        base_x, base_y = declared["base size"]
        minimum_x, minimum_y = declared["minimum size"]
        self.cell_width, self.cell_height = minimum_x - base_x, minimum_y - base_y
        self.border_x, self.border_y = base_x / 2, base_y / 2
        self.columns = (int(size["WIDTH"]) - base_x) // self.cell_width
        self.rows = (int(size["HEIGHT"]) - base_y) // self.cell_height

    def click_cell(self, column, row):
        self.read_grid()
        x = int(self.border_x + (column + .5) * self.cell_width)
        y = int(self.border_y + (row + .5) * self.cell_height)
        XvfbDisplay.input(self.owner, self.created, self.window, "mousemove", "--window",
                          str(self.window), str(x), str(y), "click", "1")

    def __exit__(self, *exception):
        try:
            if self.terminal.poll() is None:
                self.keys("ctrl+q")
                try:
                    self.terminal.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.terminal.terminate()
                    self.terminal.wait(timeout=5)
        finally:
            self.log.close()


def any_channel(text):
    return "#any · all comms" in text and "IRC / Markdown" in text


def check_typed_reply(app: TerminalApp, thread: str, output: Path) -> None:
    """A physical submit must finish in the native journal and survive tab return."""
    comms = wire()
    selected = comms.registry.require(thread)
    session = selected.runtime.history_source(comms.root, selected.incarnation)
    token = "TYPED_REPLY_" + str(time.time_ns())
    attempt = {"status": "UNKNOWN", "replay": False, "thread": thread, "token": token}
    marker = output / "typed-input.json"
    app.click_cell(app.columns // 2, app.rows - 4)
    app.type_text("Reply with " + token + ". Do not use tools.")
    # Record before Enter; a failed check must never cause this input to be replayed.
    marker.write_text(json.dumps(attempt))
    started = time.monotonic()
    app.keys("Return")

    def replies():
        return tuple(entry for entry in session.tail(max_bytes=1024 * 1024)
                     if entry.assistant_message and entry.final_reply
                     and entry.message.text.strip() == token)

    def visible(text):
        return any(cell.strip("▌ ") == token for _, cell in app.message_rows(text))

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
    app.wait("typed-return", lambda text: visible(text) and "User messages" in text)
    app.screenshot("typed-return")


def check_answer(app: TerminalApp, thread: str, answer: str) -> None:
    """The answer shows in the thread, in #any, and again back in the thread."""
    expected = "".join(answer.split())

    def visible(text):
        return expected in app.messages(text)

    app.wait("answer", visible)
    app.screenshot("answer")
    app.click("#any")
    app.wait("answer-any", lambda text: any_channel(text) and visible(text))
    app.screenshot("answer-any")
    initial = app.reader_place("any-initial")
    app.click_cell(app.columns // 2, app.rows - 4)
    app.keys("Page_Up", "Page_Up", "Page_Up")
    app.wait("any-page-up", lambda text: bool(app.reader_position(text))
             and app.reader_position(text) != initial)
    # #any lists every live agent and can push later channels off screen.
    app.toggle_group("#any")
    app.click("#comms")
    app.wait("comms", lambda text: "#comms" in "\n".join(text.splitlines()[:3]) and "IRC / Markdown" in text)
    app.toggle_group("#any")
    app.click(thread)
    app.wait("answer-return", lambda text: visible(text) and "User messages" in text)
    app.screenshot("answer-return")


def check_filtered_return(app: TerminalApp, thread: str) -> None:
    """With only the DM into the thread shown, the reader returns to the same rows from #any."""
    for category in all_categories() - {InboundCategory}:
        app.hide_category(category.label)
    expected = app.reader_place("filtered-before")
    app.screenshot("filtered-before")
    app.click("#any")
    app.wait("filtered-away", any_channel)
    app.click(BackTabButton.label)
    app.wait("filtered-return", lambda text: app.reader_position(text) == expected)
    app.click("#any")
    app.wait("filtered-click-away", any_channel)
    app.click(thread)
    app.wait("filtered-click-return", lambda text: app.reader_position(text) == expected)
    app.screenshot("filtered-click-return")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime", type=Path, required=True, help="The runtime's bin directory")
    parser.add_argument("--thread", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # The protocol owns stdout; everything else this tool prints goes to stderr.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    sys.stdout = sys.stderr
    home = Path(os.environ["HOME"])
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("AGENT_COMMS_ROOT", "AGENT_COMMS_THREAD", "XDG_"))
                   and key not in ("PYTHONPATH", "PYTHONHOME", "NO_COLOR", "TOAD_VALIDATION")}
    environment.update(XDG_CONFIG_HOME=str(home / "config"), XDG_STATE_HOME=str(home / "state"),
                       XDG_DATA_HOME=str(home / "data"), AGENT_COMMS_RUNTIME_ROOT=str(args.runtime))
    with OwnedDisplay(args.output) as display:
        command = [args.runtime / "toad"]
        with TerminalApp(command, display, args.output / "plain", environment, home) as app:
            app.wait("store", lambda text: "Toad" in text or "agent" in text.lower())
            app.screenshot("store")
        # CheckRoot restores stopped declarations. Ask the lifecycle owner to
        # start the selected worker before waiting for a connected editor.
        wire().owners.start(args.thread)
        command = [*command, "acp",
                   shlex.quote(str(args.runtime / "agent-comms-acp")),
                   wire().registry.require(args.thread).worktree,
                   "--session", args.thread, "--title", "Agent Comms"]
        with TerminalApp(command, display, args.output / "comms", environment, home) as app:
            app.wait("welcome", lambda text: args.thread in text)
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
