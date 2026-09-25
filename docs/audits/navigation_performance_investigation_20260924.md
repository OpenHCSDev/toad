# Navigation and history callback performance investigation

## Status and branch origin

This follow-up began as an investigation-only draft. It now includes the first
verified history-edge scheduling fix, shared worker-backed file previews, and
prepared code-height reuse described below. Further activation layout work remains.

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
- [x] Make file-preview highlighting/rendering use a reusable worker-backed
  component by default; the previous preview performed lexer guessing and Rich
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

## Worker-backed previews and post-spinner investigation

Python previews previously read bytes asynchronously, then guessed the lexer and
rendered/measured `Syntax` on the UI thread. `WorkerStatic` now provides a shared
worker-backed Rich component, including its ordinary `update()` entry point.
File previews use it by default through either renderer backend; Markdown files
use the existing prepared Markdown component. Heavy work starts after tab mount.
The typed task admission set is shared between the wire codec and client rather
than maintaining separate lists per transport.

The preview gate tests prove typing/navigation while file IO or CPU preparation
is blocked, unchanged-tab reuse, generic Rich table support, native Rich parity,
selection/copy, theme/source/width supersession (including reverting a pending
width), binary/error handling, viewport-bounded row rendering and closed-view disposal. The
persistent test sends the new task through two actual Toad apps sharing a service.

For an 84,027-byte Python fixture, the old path had 1,561–1,687ms maximum event-loop
gaps; the worker path had 15.83–16.35ms. UI-thread CPU over loading fell from
1,698–1,759ms to 78–82ms. These are headless heartbeat/ready-content measurements,
not terminal-presented frame timings. See `tests/file_preview_latency_pilot.py`.

The post-spinner replay fixture (`tests/cold_thread_latency_pilot.py`) records
useful settled content separately from loading UI. It still observes roughly
44ms maximum loop gaps during replay and two full reflows on updated-tab returns.
The already-warm, unchanged case can use zero full reflows. No claim of completely
warm geometry or universally sub-16ms input latency is made.

One avoidable post-preparation cost is now removed: when prepared code rows fit
their measured width, `PreparedCodeLabel` reuses their row count rather than
formatting the entire fence again to measure height. A 10,000-row width-change
fixture measured 9.572ms native versus 0.020ms prepared median CPU; wrapping and
unnormalized tabs retain native measurement. Exact native row/copy tests pass.

An additional independent foreground highlighting path was found in
`ToolCall._compose_content`: expanded Read tool results performed filename lexer
discovery and `Syntax.highlight` on the UI thread. Read results now use the same
`WorkerStatic.code()` component with filename-only discovery and the original
ANSI light/dark theme policy. Unknown filename types remain literal. Selection
and copy retain the *original* text, including trailing blank lines that Rich
does not paint. No new per-tool executor or renderer adapter was introduced.

In the same mounted-app 84,012-byte fixture, two foreground control observations
showed 370–380ms maximum event-loop gaps and 724–1,014ms UI-thread CPU. The two
worker observations showed 31–36ms gaps and 108–111ms UI-thread CPU. Mounted
ready time can be slower when worker setup/queues are cold; the change removes
input-blocking work rather than promising immediate data. Exact copy, themes,
generic worker output, hidden tool hydration, persistent service reuse and
selection tests pass. These are not terminal-presented frame measurements.

Tab-return traces still show two full reflows after some hidden Markdown updates;
the first uses transcript invalidations and the second arrives after new response
layout invalidation. A quiet unchanged return can use zero. Toad PR #10 is now
merged into this branch. Even with the integrated sidebar geometry, this branch
has not suppressed or delayed those reflows without first proving geometry/scroll
parity. Prepared data is not the same as fully mounted, current geometry.

Additional checks pass: the file-link/preview pilot, worker-preview gate pilot,
post-spinner worker gate, Markdown process/lifecycle/row pilots, renderer service
and process-pool tests, warm-up/navigation pilots, seven changed-module mypy,
changed-file fatal Ruff and whitespace checks. The post-spinner gate uses the
native headless input path while deliberately holding a replay handler; Pilot's
all-message-queues barrier would wait for that intentionally blocked handler.

The existing spinner geometry assertion failed identically on clean main
`0c79758`: it expected a near-square character grid, while merged main compensates
for approximately 2:1 terminal-cell aspect. The test now checks the intended
physical proportion and releases/drains its IO gates before temporary-file
cleanup. Production spinner rendering is unchanged.

## Pre-tab opening, close acknowledgement, and granular message filters

User feedback on the persistent PR #11 dev window separated two problems:
returning to an already-open tab is usually quick, while the first click to open
a thread sometimes delays the tab itself, before its spinner can paint. A new
read-only 40-second capture of that window (PID 2489782) finished with 47,294
all-thread samples and zero errors; 1.94s of overlapping main-thread sampled
mode-switch work included 0.88s navigation preparation and 0.60s navigation
layout. These are inclusive samples, not click-to-pixel measurements.

`open_thread_session` previously awaited canonical registry/status/session-file
discovery before creating any tab. It now mounts a minimal, closeable pending tab
and spinner **before** starting that authoritative metadata read. Once resolved,
the original typed route policy selects the existing thread, a new agent tab, or
its stopped/unresumable DM. Duplicate clicks share one resolution. Closing or
leaving the pending tab invalidates stale publication, and closing its owner
cannot strand or reopen a deleted view. A gated regression confirms a completed
loading frame and visible tab while registry I/O is still blocked. No unverified
identity is used to send messages or acknowledge a read. Clicking the already
selected loading tab does not cancel its in-flight metadata request.

For closing a large tab, an isolated four-round headless fixture observed about
20–25ms before teardown and 59–93ms for the whole close handler. Toad now removes
the tab from its visible/open order before awaiting ordinary widget teardown;
the close still awaits and completes that cleanup. This is earlier presentation,
not a claim of faster total teardown or terminal-pixel timing.

The old right-sidebar “In/out only” checkbox is now seven independent choices:
**User messages, Agent messages, Messages in, Messages out, Thinking, Tool calls,
Other / notices.** Each native message widget declares its category through the
nominal `CategorizedBlock` mixin; the filter reads that member instead of listing
every concrete widget type. Textual's custom widget metaclass prevents composing
an independent ABCMeta here. Saved events use one typed event classifier and
the existing bounded filtered-page scanner; neither live nor saved history gets
a separate parallel rendering implementation. Category changes retire derived
older-result overlays, reject stale in-flight pages, retain full underlying
history, and preserve the per-tab draft and scroll/follow intent. All non-default
filters conservatively suppress native thread read acknowledgements.

Focused mounted checks cover every category in live and saved messages, checkbox
multi-selection, unknown/notice fallback, late-arriving blocks, nested pagers,
older-page underfill and switching categories during a blocked read. The legacy
`in_out_only` property continues to select exactly the two routed categories
for existing callers; the old one-checkbox UI no longer exists. The unannotated
wire-replay test fails identically on clean baseline with the currently installed
core, before UI filtering; its explicitly annotated-route variant passes.

First-open/close checks: `tests/pending_thread_open_pilot.py`,
`tests/navigation_preparation_pilot.py`, `tests/close_session_latency_pilot.py`.
Filter checks: `tests/message_categories_pilot.py`,
`tests/message_filter_supersession_pilot.py`, `tests/in_out_filter_pilot.py`,
`tests/in_out_underfill_pilot.py`, and the annotated wire-replay pilot.

## Many-tab persistent-window stress capture

The user exercised many thread tabs in an ordinary PR #11 `20629b9` persistent
window and reported intermittent tab/close hiccups. Read-only py-spy recorded
60 seconds at 50 Hz including idle stacks: **184,757 all-thread samples,
2,999 main-thread samples, zero errors**. Saved profile:
`/home/ts/.cache/toad-pr11-20629b9-2756538-lag-20260924.json`.
The capture is complete and no profiler remains attached.

- Main-thread selector idle occupied 16.08s; layout refresh 8.96s, rendering
  7.30s, full reflow 5.26s, mode switching 5.66s, navigation preparation
  1.90s, and sidebar snapshot presentation 1.82s. Inclusive categories overlap.
- Process CPU observations were mostly 55–65%, and RSS/threads rose from
  253MiB/51 to 386MiB/81 as new tabs opened. Later read-only inspection found
  about 23 ACP child processes under this Toad instance. Every attached thread
  has its own live owner/subprocess/watchers; this interaction window is not a
  fixed-tab memory-leak measurement.
- One sampled 1.34s busy interval included ~460ms in mode switching and ~480ms
  in Textual widget mounting/styling. Such intervals may contain several events
  and are not individual click-to-pixel timings.

One avoidable contribution grows with mounted tabs: each hidden
`ThreadCommsSidebar` subscribed to global tab/mode/action observations and ran
seven-checkbox queries and identity reconciliation despite being unable to
paint. Hidden `CommsSidebar` instances likewise processed session/activity
signals. These callbacks now defer **UI row reconciliation only** until the
tab becomes active; app-owned snapshot data and the hidden history-reader path
remain intact. On activation both sidebars apply current identity, filters and
cached projection before accepting normal input.

In a mounted 10-tab, 40-observation fixture the frozen `20629b9` build ran
filter sync **42 times per hidden sidebar**; this checkpoint ran it **zero**
times on hidden sidebars while the selected sidebar updated and an older tab
caught up on return. Broad Comms, owner navigation, native/virtual sidebar,
unread and hidden-history-warmup checks pass. This counts eliminated work; it
does not by itself prove a particular terminal-frame latency.

`relationship_poll_reflow_pilot.py` still records zero redundant layouts but
3–4 incidental paints during eight unchanged polls on both the frozen baseline
and this branch. Its strict zero-paints assertion fails in both, so this change
is neither credited with fixing nor blamed for that separate existing symptom.

## First reverse revisit after opening ten tabs

The next live capture used frozen `45e36b8`, PID 2882407, configured for the
persistent renderer: 60s at 50Hz with idle stacks, 148,842 all-thread samples,
2,999 main-thread samples and zero errors. Main-thread inclusive layout was
11.80s, rendering 10.12s, mode switching 7.68s and compositor reflow 7.62s;
selector idle was 16.52s. These overlap. Profile:
`/home/ts/.cache/toad-pr11-45e36b8-2882407-active-20260924.json`.
The user clarified the sequence: create about ten tabs, revisit in reverse
creation order (slow each time), then in creation order (fast), then continue
fast back-and-forth navigation.

`tests/many_tabs_return_pilot.py` reproduces that sequence with ten saved-thread
tabs plus the original owner tab, isolated wire/config/state, a fake ACP
replay and the ordinary worker renderer. No provider or live owner is involved.
The first return mounts missing labels/close buttons and replaces sidebar
member rows whose open-session identity changed while the tab was hidden. Some
headers still contain the preceding pending-thread tab. Most stylesheet
revisions are unchanged, and later visits need no new rows. Baseline lays out
the stale roster before reconciling it, then measures the changed tree again.

The existing atomic mode-switch transaction now owns mounted-screen layout
until cached rows and tab controls have caught up. Header synchronization is
serialized with signal-driven updates and batches additions/removals. Sidebar
member replacement also retires its exact obsolete set in one DOM operation.
Underline positioning waits for committed geometry during activation. Real
resize/style/content invalidations remain pending and are measured normally;
hidden tabs do not acquire new polling or acknowledgement work.

Two sequential alternating baseline/candidate runs, same isolated fixture:

| Headless measurement | Frozen `45e36b8` | Candidate |
| --- | ---: | ---: |
| First reverse return median, run 1 / run 2 | 90.36 / 102.08ms | 82.91 / 82.71ms |
| First reverse full reflows across nine actual switches | 31 | 23 |
| Forward second-return median | 23.69–24.24ms | 16.72–17.06ms |
| Reverse third-return median | 21.18–21.52ms | 16.29–18.01ms |

The strict stale-roster-layout gate fails on frozen baseline and passes on the
candidate. It asserts ordering/readiness, not a machine-dependent timing limit.
First returns still need 2–3 full layouts as new rows and scrollbar geometry
settle. One candidate first-return maximum was 164ms versus a baseline maximum
of 120ms, and heartbeat outliers persisted. **No worst-case latency improvement,
all-tabs-always-warm claim, or terminal-pixel latency claim is made.** The
reproducible improvement is removal of obsolete layout work and lower typical
switch cost. Observations:
`/home/ts/.cache/toad-tab-returns-paired-{baseline,candidate}-{1,2}.json`.

Validation also covers empty-thread returns, real terminal resize, a same-mode
request from the screen's own message queue, closing several hidden tabs,
remaining tab order and per-tab drafts. Passed existing pilots: broad Comms,
sidebar first-frame projection, PR #10 header/sidebar geometry, sort viewport,
Back/Forward history, stylesheet revisions, pending-thread metadata, held replay
worker input/tab exit, owner navigation, close handling, hidden sidebar signals,
history scroll-frame anchoring, human read boundaries, seven categories, filter
supersession, file-preview latency and history-edge scheduling. Fatal Ruff and
whitespace checks pass. Focused mypy reports nine existing issues in
`session_tabs.py`/`sidebar_tree.py`; frozen baseline has the same issues plus one
older assignment error (ten total). `session_view.py` is clean in that check.

## Pause attribution and simultaneous scroll/selection crash

The follow-up adds optional per-operation wall/thread-CPU timings, GC callbacks,
larger wire fixtures and a native headless-display boundary to
`many_tabs_return_pilot.py`. `--display-only` avoids `Pilot.pause`'s whole-tree
callback scheduling during measured returns. `--gc-census` is a separate,
diagnostic-only retained-object census and changes collection lifetimes; it is
not used for performance comparisons. Production GC policy is untouched.

Three concrete findings:

1. **Rendered frames were discarded during navigation.** Textual's layout queues
   `_compositor_refresh`, which can execute while the atomic switch is awaiting
   mounted/resize handlers. A trace recorded 9.77ms wall / 9.72ms UI-thread CPU
   in `render_update` at batch depth 1, before `App._display` discarded that
   result. `SessionView` now retains repaint intent and dirty regions until the
   transaction ends. Every switch, including same-mode requests, wakes the
   selected screen afterward. The gate rejects such intermediate renders on
   frozen `0a7edf0` and passes with the fix.

2. **An isolated warm-return outlier was cyclic collection.** A 21.56ms switch
   with zero full layouts was followed by a 76.40ms generation-1 GC sweep,
   creating a 100.92ms heartbeat gap. A separate retained-object census found
   completed Textual workers, tasks, contexts and widget/style objects. An
   independent lifetime check proved the `Worker -> Task -> Context -> Worker`
   cycle: 100/100 completed workers remained alive until GC on baseline, versus
   0/100 when the active-worker context was restored. Executor threads also kept
   the preceding worker visible to unrelated jobs. The framework fix restores
   context in async and threaded execution, including error/cancellation paths.
   The sweep in that trace was triggered by `Pilot.pause` allocations, and
   further sweeps still occurred after the worker fix. This is a proven lifetime
   defect, **not proof that all live hangs are caused by or cured by it**.

3. **Scroll while dragging could crash the app queue.** The user supplied the
   `IndexError: pop from an empty deque` traceback from `Queue.get()` and
   identified simultaneous scrolling/highlighting. The selection coalescer
   calls `app._peek_message()` from the screen's pump. That nominal peek removed
   the queue head into another pending slot while the app could already be
   awaiting that item. Its waiter then resumed to an empty deque. The regression
   reproduces the exact traceback. Peeking now leaves the item in the queue;
   the extra pending slot is removed. `Queue.get()` also rechecks after wake-up
   to handle competing/synchronous readers without stealing or losing messages.

The framework changes are in **Textual PR #2**:
https://github.com/OpenHCSDev/textual/pull/2, pinned here at
`c56ea5604e8edb77b2ca10630db0bd354e875c3a` (an open prerequisite, not merged main).
They were tested from an isolated source worktree without installing into the
shared stack or changing a running window.

Validation: **3,080 passed, 1 skipped, 4 xfailed** for Textual outside
`tests/snapshot_tests`, including the standalone progress-bar snapshot. All 89
focused worker/queue/message-pump/selection tests pass. Baseline queue race and
worker-lifetime regressions fail. Toad's broad Comms, scroll-frame anchors,
categories, pending thread, sidebar geometry, held-renderer navigation and
two-app persistent-renderer integration pass with both source changes. Native
scroll/selection was exercised with 490 and 1,498 mounted widgets, including
offscreen selection/copy. Focused framework mypy has the same eight pre-existing
issues on baseline and candidate; fatal Ruff and whitespace checks pass.

Four display-only navigation cycles with 40 extra peers and 12 extra channels
still showed first-return medians around 113ms and a 133ms maximum; most later
returns were around 20ms. No terminal-pixel or worst-case latency guarantee is
claimed. The first-return layout/row reconciliation cost remains visible.
Detailed artifacts live in `/home/ts/.cache/toad-tab-hang-*.json`.
