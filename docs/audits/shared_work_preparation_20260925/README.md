# Shared preparation work — post-merge investigation, 2026-09-25

Worktree: `/home/ts/wt/toad-history-preparation-20260925`, branch
`perf/history-preparation-20260925`, started from merged Toad `eff5941` and now
integrated through main `a060721`. This is a **draft working candidate**, not
another merged performance fix.

## Latest follow-up: reproducibility and retained removed trees

The user manually reproduced hard hitches in the uninstrumented frozen preview
on all three paths: opening threads, opening channel/DM views, and revisiting
loaded tabs. A separate 25 Hz GIL-only profile of that preview collected 332
samples (225 main-thread), zero sampling errors. Those selected sample weights
are not a wall-clock timeline or proof of an individual frame duration.

Three isolated navigation repetitions before the main sync completed 45/46/45
actions at 306×80 cells. New-thread maxima were 324.94/226.43/215.18 ms; opening
`#any` maxima were 107.54/111.46/120.01 ms; tab-switch maxima were
127.86/240.18/369.93 ms. Four native thread targets had matching page-text/input
fingerprints across all runs. Other native pages were different or not fully
ready at the observation; channel contents changed. This establishes recurring
hitches, not a fully identical-data benchmark for every category. The earlier
704 ms GC outlier is not treated as a reproduced fixed cost.

Slow collections repeatedly ran on the UI thread: 240.20/195.35/198.74 ms wall
with 238.69/194.43/195.97 ms thread CPU for the largest collection in each run.
These were not just scheduling gaps. A separate heap census, outside timing
intervals and without forced collection, grew from about 273k to 1.36M tracked
objects between one and eleven tabs. Removed loading sidebars still accounted
for 333 closed thread rows and 135 closed channel groups in one census.

The prerequisite framework work fixes two independently reproduced owners:

Prerequisite: [Textual fork PR #3](https://github.com/OpenHCSDev/textual/pull/3),
published head `385ac01a023baaa4e97f545f4c10404fa746c538`, pinned by this draft.

1. `Signal` values close over subscribers despite weak keys. A quiet publisher
   retains removed nodes until another publish. Subscription teardown now belongs
   to the common message-pump lifecycle, including cancellation and failed
   startup, with weak reverse publisher bookkeeping.
2. `NodeList` bumped cache generations on removal but retained the obsolete
   displayed/visible child lists until another read. Destructive mutations now
   release those cached child references immediately.

The tests fail on the previous framework. Together the fixes make removed
subscribers collectible while the app/publishers remain alive. Framework suite
with xdist (`-n 2`): **3,096 passed, 1 skipped, 4 xfailed**, outside the snapshot
directory. Sixteen Toad pilots then passed with xdist against current main,
including new delivery, input attribution, formatting and thread-link checks.

### Post-sync comparison with the same updated Toad/core build

Toad main is `a060721`; the core verification worktree and isolated backend are
`956dafa`. The Textual baseline is the source of merged `06220c38`; the candidate
adds only the lifetime changes above.

| Observation | Baseline | Fixed run 1 | Fixed run 2 | Fixed run 3 |
| --- | ---: | ---: | ---: | ---: |
| Completed actions | 45 | 48 | 45 | 45 |
| Loop gap max | 223.26 ms | 178.41 ms | 285.66 ms | 242.92 ms |
| GC max | 219.87 ms | 114.16 ms | 212.89 ms | 174.17 ms |
| Tracked objects after eleven tabs | 1,343,745 | 1,166,495 | 1,223,919 | 1,239,364 |

The retained-heap reduction is encouraging, but these live runs do **not** show
a consistent worst-latency win. The baseline census listed 342 closed thread
rows and 135 closed channel groups. Full closed-widget counts in fixed runs 2/3
were 2/40 thread rows and 0/4 channel groups. Some removed objects and significant
live widget graphs remain; further lifetime and rendering work is needed.
The first pair completed its actions but exceeded a 20-second exit wait; the
later runs exited with a longer bounded cleanup wait. The census itself is an
explicit intrusive observation after the measured actions, not a UI timing claim.

### Current ownership and preview

- Toad worktree: `toad-history-preparation-20260925`, main integrated without
  conflicts; pre-sync WIP backup stash `0fdddbe4faf7b195cf98206f6c1ba77a4101beda`.
- Textual worktree: `/home/ts/wt/textual-signal-lifetime-20260925`, branch
  `perf/signal-subscription-lifetime-20260925`.
- Core verification worktree: `/home/ts/wt/comms-preparation-integration-20260925`.
- New isolated validation environment: `/home/ts/.cache/toad-main-sync-tests-314`.
- The user's visible preview is an older, frozen package in
  `/home/ts/.cache/toad-shared-work-preview-314`; it does not contain the new main
  integration or framework lifetime fixes. Its wheel SHA-256 is
  `d4d337d8c29e5d1525b48537fe5824bcd3db6cd66565679cdbf01a5e84898da8`.
  Keep that running instance intact until the user requests a replacement.

New local receipts use `/home/ts/.cache/toad-navigation-repro-{1,2,3}-*`,
`toad-navigation-widget-census-*`, and `toad-lifetime-{baseline,fixed-1,fixed-2,fixed-3}-*`.
Summaries: `/tmp/opencode/summarize-navigation-repro.py` and
`/tmp/opencode/compare-lifetime-runs.py`. The sections below retain the earlier
shared-preparation measurements with their original code/data boundaries.

## Requested architectural boundary

The user requested infrastructure-wide worker/result reuse, explicitly including
bars when their contents change between tab visits, with nominal polymorphism,
inheritance and multiple inheritance where the policies combine.

`work_preparation.py` introduces one application-owned `PreparationRuntime`:

- `PreparationWork[T]` declares identity, execution, admission lane and retention.
- `ContentAddressedWork[T]` and `ScopedWork[T]` supply distinct identity policies.
- `ThreadWork[T]` and `RendererWork[T]` supply distinct execution policies.
- `ReusableWork[T]` supplies the retention policy. Concrete operations compose
  these contracts through multiple inheritance; runtime dispatch is polymorphic.
- `ThreadRowsWork` is shared by both left and right bar projections. Worker
  results contain text, tooltips and spinner frames. `TabRosterWork` prepares
  native tab content. Each view holds its current presentation; historical work
  results and in-flight sharing belong to the runtime, not widget-local caches.
- `PreparedRenderer` makes the existing renderer API use that runtime by default.
  Pure captured-input Rich, token, transcript and diff tasks declare reuse.
  Path-aware Markdown deliberately declares fresh execution: filesystem
  observations are not versioned by source text alone.
- Worker-delivered copies prevent one consumer mutating another's cached tokens
  or nested model data. Identity hashing, result accounting and copying also run
  off-loop. There are 32 admitted jobs per model/render lane, four thread slots,
  at most 256 retained results and a 64 MiB accounted-result budget. Underlying
  renderer process admission remains in charge of actual CPU jobs.
- Cancelling a consumer does not free still-running work's admission. Shutdown
  drains owned work and closes the underlying renderer once.

`transcript_preparation.py` is now a snapshot-scoped lookahead coordinator using
the shared runtime, **not a separate per-widget result cache**. It prepares up
to eight pages ahead in each direction and stops hidden/closed speculation.
Closed snapshot scopes discard their cached data and reject late publication.
Worker preparation never mounts widgets or advances displayed/read cursors.

## Foreground publication changes

- Category visibility updates target semantic message owners, avoiding two
  whole-conversation restyles for one toggle. Native display rules, nested routed
  pagers, filter supersession and read boundaries remain covered.
- Late foreground history results cannot mount into a now-hidden tab and wait
  indefinitely for its layout.
- Tab preparation rechecks the current roster and completes the newest model
  inside the activation transaction before returning readiness.
- Sidebar intent consumes committed parent extents rather than materializing
  dirty full geometry. Navigation size bookkeeping also uses committed extents.
- `SidebarFocusOwner` is a nominal screen contract. Native/channel screens
  declare their input target; focus transfers before hiding a focused pane,
  avoiding a full geometry-sorted focus-chain reconstruction on `Hide`.
- Unscrolled relationship groups do not query global row geometry solely to
  construct a scroll anchor that would never be used.

## Measurements — useful improvements, responsiveness still unresolved

### Controlled handler fixture

On the same 502-widget fixture, synchronous category-handler CPU changed from
**150.46 ms median / 154.20 max** to **34.18 / 42.20 ms**. Whole-conversation
restyles changed from **16 to zero** over eight toggles. This is handler CPU,
not presented pixels or complete-frame settlement.

### Matched initial no-py-spy pair

Both runs completed the same 75 input actions on isolated Xvfb/st, 306×80 cells
(2149×1620 pixels), ten native tabs, the same backend pin `74e157e` and Textual
`84db4642` (source of merged `06220c38`). The retained history page coordinates
matched before and after deep scrolling. No desktop input was intercepted.

| Loop wakeup gaps ≥5 ms | Baseline | Initial shared-work candidate |
| --- | ---: | ---: |
| Overall p95 | 106.05 ms | 104.51 ms |
| Overall max | 399.09 ms | 457.08 ms |
| Filter p95 / max | 285.12 / 302.36 ms | 89.99 / 131.00 ms |
| Selection-scroll p95 / max | 60.44 / 92.92 ms | 26.90 / 48.51 ms |

The candidate had **26 cache hits and one shared in-flight request across 27
foreground history gets**. Their wall durations had median 4.05 ms, p95 35.01 ms;
those include UI scheduling delays. Final runtime counters were 359 hits,
184 misses, one shared request, 147 retained results, 14,374,276 accounted bytes.
Speculation performs additional source reads; it is bounded lookahead, not a
claim to reduce total I/O. Overall worst-case latency did not improve.

### Later geometry/focus revisions

The latest no-py-spy run completed 72 actions, using existing sidebar rows for
three overflowing-tab selections. It saw **745.52 ms** maximum loop gap and a
**703.57 ms** GC pause. Filter p95/max was 100.05/108.34 ms; selection-scroll
p95/max was 23.91/29.20 ms. History preparation had 28 cache hits and one shared
request in 29 foreground gets; median 3.36 ms. The live source advanced, so this
is **not a matched before/after comparison**. Do not hide this latest maximum
behind the better initial pair. Layout, garbage collection and allocation remain
the next bottlenecks; the 16 ms goal is not achieved.

### CPU attribution

All-thread 100/50 Hz attempts were interrupted by targeting/snapshot failures;
one sampler fell nearly three seconds behind. Those are not complete workload
latency receipts. A **50 Hz GIL-only** run completed 72 actions and collected
**3,317 samples with four sampling errors** over the requested 180 seconds.
Its sample weights describe selected GIL-holding Python stacks, not a continuous
wall-clock timeline. Per-action sample-time alignment is therefore disabled.

Exact observer counters during actions found:

| Work declaration | Submissions | Executions |
| --- | ---: | ---: |
| ThreadRowsWork | 119 | 4 |
| TabRosterWork | 27 | 18 |
| TranscriptPageWork | 248 | 79 |
| RenderPreparation | 37 | 37 |

The workload's rendered requests here were fresh inputs; do not claim renderer
cache hits from these counts. Worker reuse is directly demonstrated for both
bar work and history. About 40% of sampled main-thread GIL stacks included
`_refresh_layout`; about 32% included compositor arrangement (inclusive,
overlapping). Structured caller traces exposed eager geometry queries in focus
recovery, navigation size bookkeeping and unscrolled relationship anchoring;
the last three changes above followed that capture.

Normalized sampled stacks and structured per-action observer timings are stored
alongside this report. Transcript text/screenshots remain local diagnostics.

## Validation and caveats

The shared-runtime tests cover equivalent requests across consumers, copied
delivery, changed inputs, eviction, independent model/render lanes, cancellation
admission and single shutdown. The bar test verifies cross-consumer worker reuse
and a roster change while preparation is held. Lookahead tests cover bounded
storage, off-loop work, no-progress/error handling, late scope retirement,
data-only warming and late foreground completion after tab exit.

Focused existing checks passed for categories, routed/nested histories, older
underfill, supersession, scroll-frame anchors, human read boundaries, sidebar
focus/geometry/drag/loading continuity, many-tab returns, Comms, previews, replay,
Markdown, native message parts and teardown. Two actual Toad instances reused
one persistent renderer while completing Markdown/diff/preview/Read workflows.

There were intermittent history/Comms scheduling failures in combined runs;
isolated reruns passed. One seven-pilot runner printed all passes in 38.7 s but
the shell timed out during exit at 180 s. Do not characterize every combined
command as a clean exit. Fatal Ruff and whitespace checks have passed; a broad
typing/full-suite pass is not claimed.

## Local reproduction artifacts

- `/tmp/opencode/run-isolated-toad-workload.py`
- `/tmp/opencode/toad-expanded-live-stress.py`
- `/tmp/opencode/sidebar_validation_driver.py`
- `/home/ts/.cache/toad-history-validation-launch.sh`
- `/home/ts/.cache/toad-shared-work-{baseline,candidate,geometry-candidate,focus-candidate}-{actions,trace,state,manifest}.json`
- `/home/ts/.cache/toad-shared-work-gil.speedscope.json` and corresponding
  `toad-shared-work-gil-{actions,trace,state}.json`
- `/tmp/opencode/compare-shared-work.py`, `/tmp/opencode/analyze-work-attribution.py`

All isolated test-owned Xvfb instances/viewers were closed. The user's frozen
visible preview is separate. Core/shared-stack deployment remains owned by the
other agent. The user authorized publishing draft PRs; merging this follow-up
has not been requested. Ordinary-text `@thread_name` highlighting remains a
separate follow-up, with main's newer thread-link support included in integration.
