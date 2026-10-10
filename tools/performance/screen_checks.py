"""Check the scenario's screen-text snapshots against what the reader must see.

Each snapshot is a frame_meter.targets export: the screen's rendered text and
the visible message window. Exits non-zero, listing every violation, if:
- a "Preparing preview" row or a run of four or more blank rows is in the
  message window in any snapshot (loaded, during held PageUp, after PageUp,
  End, tab return);
- after End the window is not at its bottom following the tail;
- after tab return the window is not filled and at the tail;
- with no input, the message window's text changes between the two idle
  snapshots after held PageUp, or after the wheel bursts (the view moved by
  itself, for example while earlier history loaded above it).
"""

import json
import sys
from pathlib import Path

PLACEHOLDER = "Preparing preview"
BLANK_RUN = 4
# Window edges and message bars are drawn on every row; a row is blank when
# nothing but these remains.
EDGES = "▌▐│┃╎ "


def drawn(row: str) -> bool:
    return bool(row.strip(EDGES))


def window_rows(snapshot):
    window = snapshot["message_window"]
    x, y, width, height = window["region"]
    return [line[x:x + width] for line in snapshot["text"][y:y + height]]


def longest_blank_run(rows):
    longest = run = 0
    for row in rows:
        run = run + 1 if not drawn(row) else 0
        longest = max(longest, run)
    return longest


def main(directory):
    out = Path(directory)
    failures, seen = [], {}
    for path in sorted(out.glob("screen-*-targets.json")):
        name = path.name.removesuffix("-targets.json").removeprefix("screen-")
        snapshot = json.loads(path.read_text())
        if snapshot.get("message_window") is None:
            failures.append(f"{name}: no message window on screen")
            continue
        rows = window_rows(snapshot)
        seen[name] = {"blank_run": longest_blank_run(rows),
                      "placeholders": sum(PLACEHOLDER in row for row in rows),
                      "filled_rows": sum(drawn(row) for row in rows), "rows": len(rows),
                      **{k: snapshot["message_window"][k] for k in ("scroll_y", "max_scroll_y", "follows_tail")}}
        if seen[name]["placeholders"]:
            failures.append(f"{name}: {seen[name]['placeholders']} '{PLACEHOLDER}' rows")
        if seen[name]["blank_run"] >= BLANK_RUN:
            failures.append(f"{name}: {seen[name]['blank_run']} consecutive blank rows")
    for phase in ("pageup-idle", "wheel-idle"):
        first, second = (out / f"screen-{phase}-{n}-targets.json" for n in (1, 2))
        if first.exists() and second.exists():
            before, after = (window_rows(json.loads(path.read_text())) for path in (first, second))
            if before != after:
                moved = sum(a != b for a, b in zip(before, after))
                failures.append(f"{phase}: the view moved without input ({moved} rows changed)")
    for name in ("end", "tab-return"):
        state = seen.get(name)
        if state is None:
            failures.append(f"{name}: no snapshot")
        # Past the maximum is at the tail too: the content shrank (a finished
        # reply's throbber row) between layout and the snapshot's read.
        elif not state["follows_tail"] or state["scroll_y"] < state["max_scroll_y"]:
            failures.append(f"{name}: not at the tail (scroll {state['scroll_y']} of {state['max_scroll_y']})")
    if (state := seen.get("tab-return")) is not None and state["filled_rows"] < state["rows"] // 2:
        failures.append(f"tab-return: only {state['filled_rows']} of {state['rows']} rows drawn")
    retire = out / "retire-check.json"
    if retire.exists() and json.loads(retire.read_text())["tabs_after_delete"] >= 2:
        failures.append("retire: deleting the open thread did not close its tab")
    print(json.dumps({"snapshots": seen, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
