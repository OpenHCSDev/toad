"""Physical viewport regression capture on an isolated copy of saved history.

Run with the installed dependency interpreter and PYTHONPATH=src:<Core source>.
No provider input is submitted. The startup observer only records real geometry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


def frontend(output: Path, thread: str, project: str) -> None:
    from toad.application_lifetime import ApplicationLifetime
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import TranscriptPageView
    from toad.widgets.presentation_window import OLDER_END

    trace = (output / "geometry.jsonl").open("w", buffering=1)

    def state(window):
        return dict(y=window.scroll_y, target=window.scroll_target_y,
                    max_y=window.max_scroll_y, max_x=window.max_scroll_x,
                    follow=window.follows_tail, position=repr(window.reader_position),
                    changing=window.history_change is not None,
                    has_older=any(history.has_more(OLDER_END) for history in window.histories))

    original_watch = HistoryWindow.watch_scroll_y
    def watch(window, old, new):
        before = state(window)
        original_watch(window, old, new)
        trace.write(json.dumps(dict(at=time.monotonic(), kind="scroll", old=old, new=new,
                                    restoring=window._restoring, before=before, after=state(window))) + "\n")
    HistoryWindow.watch_scroll_y = watch
    original_place = HistoryWindow.place_reader
    def place(window):
        before = state(window)
        result = original_place(window)
        after = state(window)
        if before != after:
            trace.write(json.dumps(dict(at=time.monotonic(), kind="place", before=before, after=after)) + "\n")
        return result
    HistoryWindow.place_reader = place

    def started(lifetime):
        app = lifetime.app
        def snapshot():
            screen = app.screen
            if not hasattr(screen, "history_windows"):
                return
            windows = []
            for window in screen.history_windows:
                if not window.shown:
                    continue
                pages = []
                for page in window.query(TranscriptPageView):
                    pages.append(dict(width=page.line_width, max_x=page.max_scroll_x,
                                      widths=sorted({lines.width for lines in page.line_sets}),
                                      content_widths=sorted({lines.content_width for lines in page.line_sets}),
                                      height=page.line_count))
                windows.append(dict(**state(window), pages=pages))
            pending = output / "current.pending"
            pending.write_text(json.dumps(windows))
            pending.replace(output / "current.json")
        app.set_interval(.1, snapshot)
    ApplicationLifetime.observe_next_start(started)
    from toad.cli import main
    sys.argv = ["toad", "acp", f"{sys.executable} -m agent_comms.acp", project,
                "--title", "Agent Comms", "--session", thread]
    main()


def capture(output: Path) -> None:
    from agent_comms.check_root import CheckRoot
    from agent_comms.comms import wire
    from build_runtime import BuildDisplay, TerminalApp

    output.mkdir(parents=True)
    home = output / "home"
    home.mkdir()
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("AGENT_COMMS_", "PI_", "XDG_"))
                   and key not in ("NO_COLOR", "TOAD_VALIDATION")}
    environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
                       XDG_STATE_HOME=str(home / "state"), XDG_DATA_HOME=str(home / "data"))
    class LongHistoryCopy(CheckRoot):
        # Preserve the selected conversation, including claim acquisitions
        # preceding the ordinary 200-record check-root slice.
        max_records = 10000
        max_bytes = 64 * 1024 * 1024

    thread = os.environ.get("VIEWPORT_THREAD", "pi-cn-p3")
    with LongHistoryCopy(wire(), (thread,), output / "wire").open() as copied:
        environment["AGENT_COMMS_ROOT"] = str(copied.root)
        project = copied.registry.require(thread).worktree
        command = [sys.executable, str(Path(__file__).resolve()), "--frontend", str(output), thread, project]
        with BuildDisplay(output) as display, TerminalApp(command, display, output / "terminal", environment, home) as app:
            app.wait("ready", lambda text: thread in text and ("Saved history available" in text or "Session details · Ready" in text), seconds=45)
            app.click_cell(app.columns // 2, app.rows - 4)
            captures = []
            def record(label):
                # Capture changes as well as the settled screen to expose a bounce.
                previous = None
                started = time.monotonic()
                deadline = started + 8
                frames = []
                while time.monotonic() < deadline:
                    text = app.capture()
                    if text != previous:
                        frames.append(text)
                    if text == previous and time.monotonic() - started >= .5:
                        break
                    previous = text
                    time.sleep(.2)
                geometry = json.loads((output / "current.json").read_text())
                captures.append(dict(step=label, frames=frames, geometry=geometry))
                (output / "captures.json").write_text(json.dumps(captures, indent=2))
                with (output / "screens.txt").open("a") as log:
                    log.write(f"\n--- {label} ---\n{text}")
                return text
            record("initial")
            for index in range(int(os.environ.get("VIEWPORT_UP", "30"))):
                app.keys("Page_Up")
                record(f"up-{index + 1:02}")
            for index in range(10):
                app.keys("Page_Down")
                record(f"down-{index + 1:02}")
            app.click_cell(app.columns - 1, app.rows // 2)
            app.wait("sidebar", lambda text: "User messages" in text)
            record("sidebar-open")
            app.click_cell(app.columns // 2, app.rows - 4)
            # Continue loading earlier saved pages until the true top is reached.
            for index in range(400):
                app.keys("Page_Up")
                record(f"sidebar-up-{index + 1:02}")
                geometry = json.loads((output / "current.json").read_text())
                if geometry and all(w['y'] == 0 and not w['has_older'] for w in geometry):
                    break
            else:
                raise RuntimeError("The saved history top was not reached")
            app.screenshot("sidebar-top")
            record("sidebar-top")
            for index in range(10):
                app.keys("Page_Down")
                record(f"sidebar-down-{index + 1:02}")


if __name__ == "__main__":
    if sys.argv[1] == "--frontend":
        frontend(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        capture(Path(sys.argv[1]).resolve())
