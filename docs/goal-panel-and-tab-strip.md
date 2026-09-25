# Goal panel and tab strip follow-up

## Changes

- Rename the goal details/history action to **History**.
- Add **Collapse / Expand** as local presentation state. Collapsed controls sit
  left of the goal status/revision, wrapping in narrow panes. Snapshot refreshes
  retain the chosen presentation and keep standby/unavailable state accurate.
- Resize the goal document by dragging its existing top separator. During
  activity, the existing colored separator accepts the same gesture. Mouse
  capture preserves the drag origin, and viewport bounds keep the document
  between one row and half the terminal height. Collapse/expand retains its size.
- Remove the redundant **Scroll for full text · History** row entirely.
- Use stable tab rows: scrollbar (or empty gutter), labels, active underline.
  Keep native horizontal scrolling and verify the underline's painted highlight
  during overflow transitions, in both ANSI and RGB themes.
- Keep the resize hook optional for conversation subclasses without a goal bar,
  fixing the reproduced `CommsChatView` thread-link crash.

## Local validation

Reconciled Toad main `65339ee`, using its exact core pin `c5865e0` and Textual
pin `06220c3`. Twenty local pilot scripts passed across the final checks:
goal collapse/resize/details/edit/history/polling/separators/pause, tab geometry,
order/history/titles, existing-thread links, inbound reconciliation, current and
historical delivery, native attribution, mentions, and broad Comms.

The tab-title paint test crops by terminal cells rather than Python string
indices, preserving exact equality even when preceding labels contain wide
glyphs. The owner-pause test uses the current RuntimeServer and pause-event
contract. Targeted Ruff and whitespace checks passed.

`current_delivery_owner_pilot.py` uses the core repository's
`tests/delivery_owner_fixture.py`; include that directory on `PYTHONPATH` when
running it. A `/tmp` quota failure was handled by rerunning the tab-title pilot
with `TMPDIR=/var/tmp`; no shared files were deleted. These are local execution
receipts, without a CI wait or live owner restart.

## Real terminal correction: underline lost during overflow

The initial headless checks were insufficient. A real `st` terminal running
Toad's LinuxDriver reproduced the user's missing underline after overflow,
even though full compositor-strip queries still contained the highlight.
Moving the scrollable clip origin caused viewport-only composition to cull the
CSS-offset underline. Full-map inspection masked that error.

The correction keeps the clip at the container origin and restores the bottom
row that native scrollbar layout would otherwise consume. The scrollbar uses
the explicit empty top row; labels and underline keep their normal coordinates.

`tests/native_tab_terminal_check.py` now launches the actual application in
`st` on a private Xvfb display, uses real X mouse clicks/dragging and terminal
resizes, captures PNGs, and checks the underline pixels. It never calls
`run_test` or asks the compositor for a synthetic frame. Requirements are
`st`, `Xvfb`, `xdotool`, Pillow, and python-xlib. Run it with the installed
Toad environment:

```bash
TMPDIR=/var/tmp python tests/native_tab_terminal_check.py
```

All 11 native checks passed: before/after overflow, middle/first selection,
repaint, ANSI/RGB themes, real pointer selection, scrollbar dragging, narrow
resize and wide/no-overflow resize. The corrected screenshots were visually
inspected. Local before-fix captures are in
`/var/tmp/toad-underline-native-wbk3xk0n`; the final uninstrumented application
captures and pixel counts are in `/var/tmp/toad-native-tabs-ret2tdfj`.
This evidence supersedes the earlier headless-only claim about the underline.
