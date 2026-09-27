"""Guarded real-terminal input; observer snapshots supply read-only geometry."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import psutil
from Xlib import X, display

parser = argparse.ArgumentParser()
parser.add_argument("--window", type=lambda value: int(value, 0), required=True)
parser.add_argument("--pid", type=int, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--tabs", type=int, default=10)
parser.add_argument("--duration", type=int, default=240)
parser.add_argument("--sidebar-only", action="store_true")
parser.add_argument("--sidebar-cycles", type=int, default=4)
parser.add_argument("--resize-only", action="store_true")
parser.add_argument("--resize-sidebars", action="store_true")
parser.add_argument("--filters-only", action="store_true")
parser.add_argument("--profile-state", type=Path)
parser.add_argument("--history-only", action="store_true")
parser.add_argument("--finish-only", action="store_true")
parser.add_argument("--base-mode")
parser.add_argument("--navigation-only", action="store_true")
parser.add_argument("--open-only", action="store_true")
parser.add_argument("--wire-views", action="store_true")
parser.add_argument("--profile", type=Path)
parser.add_argument("--profile-seconds", type=int, default=180)
parser.add_argument("--profile-rate", type=int, default=50)
parser.add_argument("--profile-gil", action="store_true")
parser.add_argument("--py-spy", default="py-spy")
parser.add_argument("--profile-sudo", action="store_true")
parser.add_argument("--launcher", required=True)
parser.add_argument("--fixture-ready", type=Path)
args = parser.parse_args()
process = psutil.Process(args.pid)
identity = process.create_time()
# Toad's setproctitle clears its original argv/environ. Verify the launching
# terminal and the inherited observer identity on its native ACP child instead.
assert process.cmdline()[0] == "toad"
assert args.launcher in process.parent().cmdline()
if args.fixture_ready:
    receipt = json.loads(args.fixture_ready.read_text())
    assert receipt["pid"] == args.pid and receipt["driver"] == "sidebar_validation_driver:ValidationDriver"
else:
    assert any(child.environ().get("TEXTUAL_DRIVER") == "sidebar_validation_driver:ValidationDriver"
               and child.environ().get("TOAD_VALIDATION_SNAPSHOT") == str(args.snapshot)
               for child in process.children(recursive=True))
connection = display.Display()
window = connection.create_resource_object("window", args.window)
geometry = window.get_geometry()
assert int(window.get_full_property(connection.intern_atom("_NET_WM_PID"), X.AnyPropertyType).value[0]) == process.ppid()
root = connection.screen().root
active_atom = connection.intern_atom("_NET_ACTIVE_WINDOW")
actions, snapshots = [], []
report = {"window": args.window, "pid": args.pid, "actions": actions,
          "snapshots": snapshots, "completed": False, "py_spy": bool(args.profile),
          "display": os.environ.get("DISPLAY"), "pixels": [geometry.width, geometry.height]}
deadline = time.monotonic() + args.duration
intended_mouse = None
profiler = None


def control_profile(expected):
    if args.profile_state is None:
        return
    guard()
    os.kill(args.pid, signal.SIGRTMIN)
    until = time.monotonic() + 15
    while time.monotonic() < until:
        try:
            receipt = json.loads(args.profile_state.read_text())
            if receipt["pid"] == args.pid and receipt["status"] == expected:
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.05)
    raise TimeoutError(f"Focused profiler did not become {expected}")


def guard():
    assert time.monotonic() < deadline, "Bounded input interval expired"
    assert process.is_running() and process.create_time() == identity, "Process identity changed"
    active = root.get_full_property(active_atom, X.AnyPropertyType)
    focused = int(active.value[0]) if active is not None else connection.get_input_focus().focus.id
    assert focused == args.window, "Focus changed"
    current = window.get_geometry()
    assert (current.width, current.height) == (geometry.width, geometry.height), "Size changed"
    if intended_mouse is not None:
        pointer = window.query_pointer()
        assert (pointer.win_x, pointer.win_y) == intended_mouse, f"Pointer moved: expected {intended_mouse}, actual {(pointer.win_x, pointer.win_y)}"


def state(label=None):
    guard()
    requested = time.monotonic_ns()
    os.kill(args.pid, signal.SIGUSR1)
    until = time.monotonic() + 6
    while time.monotonic() < until:
        guard()
        try:
            current = json.loads(args.snapshot.read_text())
            if current["ns"] >= requested and current["pid"] == args.pid:
                if label:
                    snapshots.append({"label": label, **current})
                time.sleep(.04)
                return current
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.02)
    raise TimeoutError("UI snapshot did not arrive")


def point(snapshot, rect, *, dx=None, dy=None):
    x, y, width, height = rect
    columns, rows = snapshot["size"]
    cw, ch = geometry.width // columns, geometry.height // rows
    px, py = (geometry.width-columns*cw)//2, (geometry.height-rows*ch)//2
    return (int(px+(x+(width/2 if dx is None else dx))*cw),
            int(py+(y+(height/2 if dy is None else dy))*ch))


def command(*parts):
    guard()
    subprocess.run(["xdotool", *map(str, parts)], check=True)


def move(position):
    global intended_mouse
    command("mousemove", "--window", args.window, *position)
    intended_mouse = position
    time.sleep(.04)


def action(name, operation, settle=.4):
    guard()
    if args.profile_state is not None:
        control_profile("running")
    row = {"action": name, "start_ns": time.monotonic_ns()}
    try:
        operation()
        until = time.monotonic() + settle
        while time.monotonic() < until:
            time.sleep(.04)
            guard()
        row["completed"] = True
    finally:
        row["end_ns"] = time.monotonic_ns()
        actions.append(row)
        if args.profile_state is not None:
            control_profile("complete")


def click():
    command("mousedown", 1, "mouseup", 1)


def wheel(button, count):
    for _ in range(count):
        command("mousedown", button, "mouseup", button)
        time.sleep(.035)


def bar(snapshot, side):
    return next(w for w in snapshot["widgets"] if w.get("sidebar") == side)


def toggle(side):
    before = state()
    widget = bar(before, side)
    move(point(before, widget["rect"]))
    action(f"toggle:{side}", click)
    after = state()
    assert after["mode"] == before["mode"], "View changed during sidebar toggle"
    assert after["tabs"] == before["tabs"], "Tab roster changed during sidebar toggle"
    assert bar(after, side)["collapsed"] != widget["collapsed"], "Toggle did not change state"
    return after


def reveal(side):
    snapshot = state()
    return toggle(side) if bar(snapshot, side)["collapsed"] else snapshot


def resize_sidebar(side, delta_percent):
    before = reveal(side)
    handle = next(widget for widget in before["widgets"] if widget.get("resize_sidebar") == side)
    initial = handle["width_percent"]
    start = point(before, handle["rect"], dx=.5, dy=3)
    direction = -1 if handle["right"] else 1
    delta = round(geometry.width * delta_percent / 100) * direction
    move(start)

    def drag():
        global intended_mouse
        command("mousedown", 1)
        try:
            for step in range(1, 17):
                target = (start[0] + round(delta * step / 16), start[1])
                command("mousemove", "--window", args.window, *target)
                intended_mouse = target
                time.sleep(.016)
        finally:
            subprocess.run(["xdotool", "mouseup", "1"], check=True)

    action(f"resize:{side}:{delta_percent:+}", drag, .7)
    after = state(f"resized:{side}:{delta_percent:+}")
    updated = next(widget for widget in after["widgets"] if widget.get("resize_sidebar") == side)
    assert (updated["width_percent"] - initial) * delta_percent > 0, (initial, updated)
    assert after["mode"] == before["mode"] and after["tabs"] == before["tabs"]
    assert not after["mouse_captured"], "Resize handle did not release pointer capture"


def filter_threads(modes):
    assert args.fixture_ready is not None
    receipt = json.loads(args.fixture_ready.read_text())
    assert receipt["fixture_kind"] == "all-categories"
    categories = tuple(receipt["category_counts"])
    assert len(categories) == 7 and all(receipt["category_counts"].values())
    expected = {mode: set(categories) for mode in modes}
    drafts = {mode: "" for mode in modes}

    def visible_matches(snapshot, mode):
        shown = {widget["message_category"] for widget in snapshot["widgets"] if "message_category" in widget}
        return snapshot["conversation"]["filter_pending"] or shown <= expected[mode]

    def verify(snapshot, mode):
        assert snapshot["mode"] == mode
        assert set(snapshot["conversation"]["visible_categories"]) == expected[mode]
        assert snapshot["conversation"]["draft_text"] == drafts[mode], (mode, snapshot["conversation"]["draft_text"], drafts[mode])
        checkbox_values = {widget["id"].removeprefix("filter-"): widget["checked"]
                           for widget in snapshot["widgets"] if widget["kind"] == "Checkbox"}
        assert all(checkbox_values[category] == (category in expected[mode]) for category in categories)
        if not snapshot["conversation"]["filter_pending"]:
            shown = {widget["message_category"] for widget in snapshot["widgets"] if "message_category" in widget}
            assert shown <= expected[mode], (shown, expected[mode])

    def change(mode, category, enabled, *, type_during=False, rapid=False):
        before = state()
        checkbox = next(widget for widget in before["widgets"] if widget["id"] == f"filter-{category}")
        assert checkbox["checked"] != enabled
        prompt = next(widget for widget in before["widgets"] if widget["kind"] == "PromptTextArea")
        position = point(before, checkbox["rect"], dx=1, dy=.5)
        prompt_position = point(before, prompt["rect"], dx=1, dy=.5)
        move(position)

        def interact():
            click()
            if rapid:
                command("click", "--repeat", "2", "--delay", "20", 1)
            if type_during:
                global intended_mouse
                command("mousemove", "--window", args.window, *prompt_position)
                intended_mouse = prompt_position
                click()
                command("type", "--clearmodifiers", "--delay", 0, "x")

        action(f"filter:{mode}:{category}:{enabled}" + (":rapid" if rapid else ""), interact, .15)
        if enabled:
            expected[mode].add(category)
        else:
            expected[mode].discard(category)
        if type_during:
            drafts[mode] += "x"
        after = state(f"filtered:{mode}:{category}:{enabled}")
        # A refresh callback isn't an input-queue barrier. Wait for the actual
        # queued character with a bounded deadline; native key-to-apply latency
        # is recorded separately by the observer, rather than guessed here.
        until = time.monotonic() + 1
        while ((type_during and after["conversation"]["draft_text"] != drafts[mode])
               or not visible_matches(after, mode)) and time.monotonic() < until:
            after = state()
        verify(after, mode)
        actions[-1]["end_ns"] = time.monotonic_ns()
        actions[-1]["acknowledged"] = True

    # Different thread-local masks, including all-off, with typing immediately
    # after checkbox clicks. The test never submits the draft to an agent.
    for index, mode in enumerate(modes):
        switch(mode)
        reveal("thread-sidebar")
        verify(state(), mode)
        for category in categories:
            change(mode, category, False, type_during=True)
        change(mode, categories[index % len(categories)], True)
    # Revisit every thread while its filtered history may still be scanning,
    # then restore each category using a rapid off/on/off or on/off/on burst.
    for mode in reversed(modes):
        switch(mode)
        reveal("thread-sidebar")
        verify(state(), mode)
        for category in categories:
            if category not in expected[mode]:
                change(mode, category, True, type_during=True, rapid=True)
        verify(state(f"filters-restored:{mode}"), mode)
    report["filter_verification"] = {"categories": list(categories), "modes": modes,
                                      "draft_lengths": {mode: len(text) for mode, text in drafts.items()},
                                      "restored_all": all(selected == set(categories) for selected in expected.values())}


def switch(mode):
    for _ in range(40):
        snapshot = state()
        modes = [m for m, _ in snapshot["tabs"]]
        assert mode in modes, f"Requested tab disappeared before navigation: {mode}"
        if os.environ.get("TOAD_REVISIT_SIDEBAR") == "1":
            row = next((w for w in snapshot["widgets"] if w["kind"] == "ThreadRow"
                        and w.get("mode") == mode and w["rect"][2] >= 4), None)
            if row is not None:
                move(point(snapshot, row["rect"], dx=3, dy=.5))
                action(f"switch-sidebar:{mode}", click, .55)
                result = state(f"switched:{mode}")
                if result["mode"] == mode:
                    return result
                continue
        labels = [w for w in snapshot["widgets"] if w["kind"] == "SessionLabel"]
        tab = next((w for w in labels if w["id"] == mode and w["rect"][2] >= 3), None)
        if tab:
            move(point(snapshot, tab["rect"]))
            # Tab auto-centering may still be animating after a mode switch.
            # Re-read committed geometry instead of clicking a stale rectangle.
            time.sleep(.15)
            refreshed = state()
            latest = next((w for w in refreshed["widgets"] if w["kind"] == "SessionLabel" and w["id"] == mode), None)
            if latest is None or latest["rect"] != tab["rect"]:
                continue
            action(f"switch:{mode}", click, .55)
            result = state(f"switched:{mode}")
            if result["mode"] == mode:
                return result
            report.setdefault("navigation_retries", []).append({"requested": mode, "observed": result["mode"]})
            continue
        modes = [m for m, _ in snapshot["tabs"]]
        row = next((w for w in snapshot["widgets"] if w["kind"] == "ThreadRow"
                    and w.get("mode") == mode and w["rect"][2] >= 4), None)
        if row is not None:
            move(point(snapshot, row["rect"], dx=3, dy=.5))
            action(f"switch-sidebar:{mode}", click, .55)
            result = state(f"switched:{mode}")
            if result["mode"] == mode:
                return result
            continue
        if mode == snapshot["mode"]:
            time.sleep(.15)
            continue
        # The strip does not accept wheel scrolling. Clicking a nearer exposed
        # tab uses its normal auto-centering to reveal the next group of tabs.
        nearer = [w for w in labels if w["id"] in modes and w["rect"][2] >= 3
                  and abs(modes.index(w["id"]) - modes.index(mode))
                  < abs(modes.index(snapshot["mode"]) - modes.index(mode))]
        if not nearer:
            time.sleep(.15)
            continue
        edge = min(nearer, key=lambda w: abs(modes.index(w["id"]) - modes.index(mode)))
        move(point(snapshot, edge["rect"]))
        action(f"switch-step:{edge['id']}", click, .4)
    raise AssertionError(f"Tab could not be exposed through native scrolling: {mode}")


def history(snapshot):
    return next(w for w in snapshot["widgets"] if w["kind"] in ("Window", "HistoryWindow"))


def select_scroll():
    global intended_mouse
    text = None
    for _ in range(12):
        snapshot = state()
        text = next((w for w in snapshot["widgets"] if w["kind"] == "MarkdownParagraph" and w["rect"][2] >= 10), None)
        if text is not None:
            break
        move(point(snapshot, history(snapshot)["rect"]))
        action("find-selection:scroll-history", lambda: wheel(4, 8), .4)
    assert text is not None, "No visible paragraph for selection"
    move(point(snapshot, text["rect"], dx=1, dy=.5))
    end = point(snapshot, text["rect"], dx=8, dy=.5)

    def gesture():
        global intended_mouse
        command("mousedown", 1)
        try:
            command("mousemove", "--window", args.window, *end)
            intended_mouse = end
            time.sleep(.04)
            wheel(4, 8)
        finally:
            subprocess.run(["xdotool", "mouseup", "1"], check=True)
    action("select-and-scroll", gesture, .7)
    after = state("after-selection")
    assert after["mode"] == snapshot["mode"], "Selection changed the active view"
    assert [m for m, _ in after["tabs"]] == [m for m, _ in snapshot["tabs"]], "Selection changed the tab roster"


try:
    guard()
    time.sleep(2)
    if args.profile:
        report["profile_request_ns"] = time.monotonic_ns()
        report["profile_rate_hz"] = args.profile_rate
        report["profile_gil_only"] = args.profile_gil
        report["profile_duration_s"] = args.profile_seconds
        profiler = subprocess.Popen([*(["sudo", "-n"] if args.profile_sudo else []), args.py_spy, "record",
                                     "--pid", str(args.pid), "--duration", str(args.profile_seconds),
                                     "--rate", str(args.profile_rate), "--idle", "--format", "speedscope",
                                     "--output", str(args.profile), *(["--gil"] if args.profile_gil else [])])
        time.sleep(1)
        assert profiler.poll() is None, "Profiler failed to attach"
    initial = state("initial")
    base_mode = args.base_mode or initial["mode"]
    initial_bars = {side: bar(initial, side)["collapsed"] for side in ("channels-sidebar", "thread-sidebar")}
    for _ in range(0 if args.resize_only or args.filters_only else args.sidebar_cycles if args.sidebar_only else 4):
        toggle("channels-sidebar")
        toggle("thread-sidebar")
    if not args.sidebar_only and not args.history_only and not args.finish_only and not args.resize_only:
        attempted = set()
        for _ in range(70):
            snapshot = reveal("channels-sidebar")
            if len(snapshot["tabs"]) >= args.tabs:
                break
            if args.wire_views:
                rows = [w for w in snapshot["widgets"] if w.get("target") not in attempted
                        and ((w["kind"] == "ThreadRow" and w.get("row_kind") == "dm")
                             or (w["kind"] == "CommsRow" and w.get("row_kind") in {"channel", "irc"}))]
                rows.sort(key=lambda row: row["kind"] == "ThreadRow")
            else:
                rows = [w for w in snapshot["widgets"] if w["kind"] == "ThreadRow"
                        and w.get("mode") is None and w["target"] not in attempted
                        and w["row_kind"] == "thread"]
            if rows:
                row = rows[0]
                attempted.add(row["target"])
                move(point(snapshot, row["rect"], dx=min(3, row["rect"][2]/2), dy=.5))
                action(f"open:{row['target']}", click, 1.8)
                for _ in range(25):
                    ready = state()
                    conversation = ready.get("conversation", {})
                    assert not conversation.get("errors"), conversation.get("errors")
                    if args.wire_views:
                        if ready.get("channel_history", {}).get("initialized"):
                            break
                    elif conversation.get("agent_ready") and not conversation.get("loading"):
                        assert ready["histories"] or conversation.get("content_blocks", 0), "Ready view has no content"
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError(f"View did not load successfully: {row['target']}: {ready.get('conversation')}")
                state(f"opened:{row['target']}")
            else:
                panel = next(w for w in snapshot["widgets"] if w["id"] == "channels-sidebar" and "sidebar" not in w)
                move(point(snapshot, panel["rect"], dx=8))
                action("find-row:scroll-sidebar", lambda: wheel(5, 4), .25)
        snapshot = state("many-tabs")
        assert len(snapshot["tabs"]) >= args.tabs, "Requested tab count was not reached"
        modes = [mode for mode, _ in snapshot["tabs"]]
        if not args.open_only and not args.filters_only:
            for mode in list(reversed(modes)) + modes:
                switch(mode)
    if args.navigation_only:
        snapshot = reveal("channels-sidebar")
        target = next(w for w in snapshot["widgets"] if w["kind"] == "CommsRow"
                      and w.get("row_kind") in ("channel", "irc") and w["rect"][2] >= 5)
        previous_mode = snapshot["mode"]
        move(point(snapshot, target["rect"], dx=3, dy=.5))
        action(f"open-channel:{target['target']}", click, 2.0)
        snapshot = state("channel-opened")
        assert snapshot["mode"] != previous_mode and snapshot["screen"] == "CommsScreen"
        channel_mode = snapshot["mode"]
        for mode in (base_mode, channel_mode, base_mode, channel_mode, base_mode):
            switch(mode)
    if args.resize_only or args.resize_sidebars:
        if not args.resize_only:
            switch(base_mode)
        for _ in range(2):
            for side in ("channels-sidebar", "thread-sidebar"):
                resize_sidebar(side, 5)
                resize_sidebar(side, -5)
    if args.filters_only:
        filter_threads([mode for mode, _ in state("filter-tabs")["tabs"]][:args.tabs])
    if not args.sidebar_only and not args.finish_only and not args.navigation_only and not args.open_only and not args.resize_only and not args.filters_only:
        modes = [mode for mode, _ in state()["tabs"]]
        switch(base_mode)
        assert len(state()["tabs"]) >= args.tabs, "Tab count changed before history checks"
        for index in range(10):
            snapshot = state(f"before-deep-scroll:{index}")
            move(point(snapshot, history(snapshot)["rect"]))
            action(f"deep-scroll:{index}", lambda: wheel(4, 36), .55)
            after = state(f"after-deep-scroll:{index}")
            assert after["mode"] == base_mode and len(after["tabs"]) >= args.tabs, "View/roster changed during scrolling"
            if index in (2, 6, 9):
                toggle("channels-sidebar")
                toggle("thread-sidebar")
        select_scroll()
        reveal("thread-sidebar")
        for category in ("tool", "thinking", "agent", "user"):
            snapshot = state()
            assert snapshot["mode"] == base_mode and any(h["fragments"] for h in snapshot["histories"]), "Filters require the loaded target history"
            checkbox = next(w for w in snapshot["widgets"] if w["id"] == f"filter-{category}")
            initial_value = checkbox["checked"]
            for expected in (not initial_value, initial_value):
                snapshot = state()
                checkbox = next(w for w in snapshot["widgets"] if w["id"] == f"filter-{category}")
                move(point(snapshot, checkbox["rect"], dx=1, dy=.5))
                action(f"filter:{category}:{expected}", click, .9)
                result = state(f"filter:{category}:{expected}")
                assert result["mode"] == base_mode and len(result["tabs"]) >= args.tabs, "View/roster changed during filtering"
                assert next(w for w in result["widgets"] if w["id"] == f"filter-{category}")["checked"] == expected
    if not args.sidebar_only and not args.navigation_only and not args.open_only and not args.resize_only and not args.filters_only:
        modes = [mode for mode, _ in state()["tabs"]]
        select_scroll()
        for _ in range(3):
            toggle("channels-sidebar")
            toggle("thread-sidebar")
        for mode in (modes[-1], base_mode):
            switch(mode)
    for side, collapsed in initial_bars.items():
        if bar(state(), side)["collapsed"] != collapsed:
            toggle(side)
    state("final")
    report["completed"] = True
except BaseException as error:
    report["error"] = f"{type(error).__name__}: {error}"
    raise
finally:
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    connection.close()
    print({"completed": report["completed"], "actions": len(actions), "error": report.get("error")})
    if profiler is not None:
        print({"profiler_exit": profiler.wait(timeout=args.profile_seconds + 10)})
