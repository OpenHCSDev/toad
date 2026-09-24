# Navigation and history callback performance investigation

## Status and branch origin

This follow-up began as an investigation-only draft. It now includes the first
verified history-edge scheduling fix described below; preview rendering and
activation layout work remain in progress.

- Repository: `OpenHCSDev/toad`; target branch: `main`.
- Freshly fetched starting commit:
  `e3f86d889e2a94f920077c76b5b7e0ac93a3f9a7` (merged Toad PR #9).
- Investigation branch: `perf/navigation-readiness-investigation`.
- Isolated worktree: `/home/ts/wt/toad-navigation-performance-20260924` (moved
  from `/tmp/opencode` after the tmpfs user quota was exhausted).
- Subsequently merged remote main `0c79758`, including the reviewed core pin,
  into this branch with an ordinary merge.
- The earlier Toad/Textual PR #1 implementations are merged history. This is new
  work on current main, not a continuation of an archived private worktree.
- Another agent owns [agent-comms PR #12](https://github.com/OpenHCSDev/agent-comms/pull/12),
  covering ACP/runtime input errors, paging capability forwarding and stack work.
  This investigation's proposed implementation scope is Toad-side scheduling and
  navigation. Any framework-owned fix needs a separately scoped Textual change.
- [Toad PR #10](https://github.com/OpenHCSDev/toad/pull/10) is a separate
  screenshot-driven UI issue tracker, currently documentation-only. Coordinate
  overlapping widget changes before beginning implementation in either branch.

The user reports a substantial overall improvement but intermittent slow returns
to open tabs. The <16 ms useful terminal-frame target remains an ongoing goal,
separate from the correctness and integration requirements for incremental fixes.

## Repeated live capture comparison

All four captures sampled **the same Toad PID 1558512** for 60 seconds at 50Hz
using read-only py-spy with idle/wait stacks enabled. The first and fourth captures
included user interaction; the user reported being distracted during the middle
two, which serve as idle observations. Every capture reported zero sampling errors.

Captured source paths are under
`/home/ts/.agent-comms/stack/.venv/lib/python3.14/site-packages/`.
An exact runtime source hash was not recorded, so these are installed-stack
diagnostics, not benchmarks attributed to this branch's exact main commit.

| Observation | First busy capture | Latest busy capture | Idle captures |
| --- | ---: | ---: | ---: |
| All-thread samples | 80,187 | 136,082 | 107,964 each |
| Main-thread samples | 2,999 | 2,999 | 2,999 each |
| Selector idle | 32.86 s | 25.96 s | 55.32 / 55.88 s |
| Layout refresh, including painting | 11.02 s | 7.54 s | 0.02 / no samples |
| Rendering updates | 7.18 s | 6.38 s | 0.04 / no samples |
| Full compositor reflow | 4.42 s | 3.42 s | no samples |
| Mode-switch execution | 2.10 s | 3.34 s | no samples |
| Navigation preparation | 0.74 s | 0.96 s | no samples |
| Navigation layout | 0.64 s | 1.80 s | no samples |
| Main-thread store-lock path | 0.02 s | no samples | no samples |
| Five-second CPU observations | 27.4–76.8% | 28.6–82.8% | 8.6–11.6% |
| RSS observations | 192.5→251.9 MiB | 280.4→313.9 MiB | flat at 252.2 / 253.4 MiB |
| Thread counts | 19→36 | 39→52 | 36 |

Sampled call categories are **inclusive and overlapping**, not additive. Manual
interaction sequences and the number of open views differ. These observations
do not establish a speedup/regression, exact individual-frame latency, or a leak.
The idle plateaus show that growth paused in those intervals, not that retention
is bounded under all workloads. Main-thread samples can miss short lock waits.

Raw profiles remain local, named under `/home/ts/.cache/`:

- `toad-1558512-running-profile-20260924.json` — first busy capture.
- `toad-1558512-running-profile-20260924-repeat2.json` — idle.
- `toad-1558512-running-profile-20260924-repeat3.json` — idle.
- `toad-1558512-running-profile-20260924-repeat4.json` — latest busy capture.

All profilers are stopped. This profiling session made no live application or
environment changes while collecting these captures.

## Finding 1: possible no-progress history-edge callback loop

The latest capture has a 1.50-second consecutive non-selector sampled interval
at 34.74–36.24s. Within it, samples include approximately:

- 580 ms in the screen's after-refresh callback processing;
- 420 ms in callback parameter counting, including signature inspection;
- 240 ms in `CommsChatView._on_window_scroll`;
- 240 ms in message-dispatch method lookup.

These overlap and may cover many callbacks; this is not a timed single freeze.
They identify callback work worth investigating in addition to layout/painting.

Current-main source provides a concrete hypothesis:

1. `src/toad/widgets/comms_chat.py:_on_window_scroll` schedules an edge load when
   the viewport is near an edge with more history available.
2. `_load_history_edge` returns immediately if `_refresh_lock` is held.
3. Its `finally` block nevertheless clears `_edge_load_scheduled` and unconditionally
   calls `call_after_refresh(self._on_window_scroll)`.
4. `_refresh` can hold that lock across asynchronous page/coordination reads.

The no-progress loop was reproduced on the main-based code: **1,617 edge-load
attempts in 250ms**, with **248.89ms UI-thread CPU**, while the refresh lock was
held. This proves the bug, though not that every captured delay came from it.

The fix keeps one widget-owned worker waiting for the lock, rather than blocking
the widget message pump or rearming a callback on every unsuccessful attempt.
It rechecks the latest viewport after admission, defers hidden-view loading until
return, rejects late publication after tab exit/route change, and automatically
rearms only after actual page/cursor progress. Empty/duplicate/error responses do
not create an immediate retry loop.

The same fixture now records **one attempt in 250ms** and **28.44ms UI-thread
CPU**. Timing includes normal fixture rendering/polling and is not terminal-pixel
latency. Regression coverage includes typing while blocked, older/newer paging,
latest viewport intent, no-progress/error responses, tab exit/return, late IO,
close/cancellation and underfilled-page loading.

## Finding 2: data readiness does not imply activation readiness

Current-main `src/toad/app.py:_switch_mode_ready` awaits navigation preparation
and layout inside a serialized mode switch and batched presentation transaction.
In `src/toad/screens/session_view.py`:

- Invalid hidden content/geometry causes `_screen_resized` to take full reflow.
- `prepare_navigation` restores sidebar state and presents cached session rows.
- `layout_navigation` can perform full layout, restore scroll, await resize/show
  handlers and perform another full layout before completing activation.

Hidden history preparation in `CommsChatView` prepares page data; it does not
guarantee that the resulting mounted geometry is already current. The latest
capture's increased sampled navigation work supports measuring these stages
separately. Simply running unrestricted hidden layouts would compete with input.

Second implementation candidate: identify redundant invalidations/reflows and
reuse valid geometry while keeping genuinely required content, width, theme and
sidebar changes correct. Any additional preparation must be bounded and must
not monopolize the event loop during unrelated interactions.

## Implementation and validation plan

- [x] Reproduce an edge-scroll request while a current-view refresh is held at
  an asynchronous gate; count callbacks, page reads and event-loop progress.
- [x] Verify eventual paging after gate release, older/newer edges, underfilled
  pages, no-progress/error cases, tab exit, close/cancellation and latest scroll intent.
- [x] Implement a bounded, completion-driven scheduling fix.
- [ ] Make file-preview highlighting/rendering use a reusable worker-backed
  component by default; the current preview performs lexer guessing and Rich
  Syntax rendering on the UI thread after its asynchronous file read.
- [ ] Instrument layout invalidation reasons and full/visible reflow counts for
  quiet returns, hidden-data updates, sidebar changes, resize and theme changes.
- [ ] Remove confirmed redundant foreground work with focused regressions.
- [ ] Re-run relevant existing pilots: `history_scroll_frames_pilot.py`,
  `channel_unread_follow_pilot.py`, `owner_navigation_pilot.py`,
  `navigation_preparation_pilot.py`, `navigation_source_timer_pilot.py`, and
  sidebar layout/scroll checks. Add scoped read-boundary checks if touched.
- [ ] Validate same-scene native output, selection/copy, drafts, full history,
  scroll/follow and canonical routing. Preserve merged display-basis/read checks;
  hidden preparation never acknowledges reads.
- [ ] Compare before/after on isolated test data and the intended installed stack.
  Report useful terminal pixels separately from headless display/flush timings.

Likely initial source scope: `src/toad/widgets/comms_chat.py` and focused tests.
Layout follow-up scope: `src/toad/screens/session_view.py`, with `src/toad/app.py`
only if the measured transaction boundary requires it. Coordinate any scope
expansion with current owners before editing shared integration paths.

## Validation at draft creation

Completed: fresh-main provenance check, comparison of saved live captures,
read-only inspection of current source, and document whitespace review.
The initial commit was documentation-only. The first implementation checkpoint
passes `history_edge_scheduling_pilot.py`, `channel_unread_follow_pilot.py`,
`history_scroll_frames_pilot.py`, `channel_background_warmup_pilot.py`,
`owner_navigation_pilot.py`, changed-file fatal Ruff and whitespace checks.
