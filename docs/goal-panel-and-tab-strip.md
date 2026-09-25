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
