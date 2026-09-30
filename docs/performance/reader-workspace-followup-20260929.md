# Reader and workspace continuation

Owner: Heisenberg. Base: main `4c20f882402e53ca6e685e8bd6c29d831b86cc05`,
including source-operation #210 and reader checkpoint #213. This work continues
the existing presentation, viewport, editor and workspace owners.

## Published checkpoint

#213 deleted 19 production lines and added 17 across `history_anchor.py`,
`transcript_publication.py` and `session_presentation.py`. All three files have
zero production difference between main43949 and main210 before #213. The tested
source65 and receipt-only609 therefore enter main without a competing reader
implementation. Parent owns paired staging and activation.

The installed read-only saved-source journey passed 351 completed compositor
frames. Repeated PageDown contributed 174 frames, 36 during loading and 87 with
newer history; three had both. Native maximum ranged from 23 to 131 rows.
Reverse contributed 146 frames; separate End contributed nine. There were no
blank destination bodies or scroll positions outside native extent. Physical
A/B/A retained the same history and all three return paints matched the reader.
These results ship the useful reader correction; they do not close every void
case, held terminal playback, CPU attribution or full TC1.

## Remaining acceptance and crossings

Primary void acceptance is held/repeated PageDown at a growing lazy end, then
reverse and idle. End is a separate destination check. Inspect completed paint,
including partial blank regions and body progression, through the existing
terminal recorder. Correlate physical inputs, activation/preparation/layout/paint
and UI/worker CPU on one monotonic timeline. Use a short unprofiled comparison.

PR214 owns the existing adaptive preparation implementation: measured direction,
velocity, body delivery, bounded worker lookahead and destination demand. Reuse
its normally integrated published checkpoint, preserving its worktree. Do not
create another preparation pool, renderer, page buffer or scroll bound.

Schrodinger426 owns source-operation/recovery custody. Arendt425 owns canonical
turn, goal, status, input permission and cancel. Coordinate shared methods before
edits. Main210's WorkingTranscript replaces loading/advancing flags; this driver
observes that owner directly rather than restoring an alias. Its primary
assertions now require both an admitted lazy read and changing native extent.

Continue TC1/T9 workspace lifetime and typed layout ownership, reader/extent
void investigation, focus/key delivery and retained presentation performance.
Resources may retain bounded trees, render output and editor document/undo;
they must not copy model/goal/turn/source status. Preserve failed-view history,
draft and undo through the existing source invalidation contract. Delete replaced
definitions and every consumer. Per-function/file dispatch ratchets remain
bounded to the actual write set; no broad repeated suite or final50ms gate.

## Resource custody

Work stays in `/home/ts/wt/toad-retained-outer-history-first-paint-20260929`.
Existing `.artifacts/reader-readonly` contains retained successful receipts and
the interrupted original private UI state. Preserve both. Approved default ACP
attaches existing source owners; no prompts, owner starts/restarts/stops, original
input replay or global package mutations. Check resources before serial capture.
