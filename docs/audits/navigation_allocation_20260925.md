# Post-merge navigation allocation investigation — 2026-09-25

## Current tracking checkpoint — supersedes historical status below

### Filter display constraints and bounded worker admission — follow-up

Framework dependency for this follow-up: `9ff47a7eb222593bcc9549552e1cf9bab2a5d45a`
([Textual PR #5](https://github.com/OpenHCSDev/textual/pull/5)).

Ordinary category toggles now use Textual's composable display constraints rather
than CSS matching. Custom marker selectors still receive native style updates;
authored display rules are preserved. Filtered-history selection now runs through
the shared preparation runtime and admits at most four matches per publication,
retaining only data for the rest of that source page. Generation checks protect
preparation and both mount awaits. This does **not** bound cumulative overlay or
direct live-widget growth; the source-size-independent presentation task is open.

Fresh private-data replay control uses the published source pair Toad `4e2ecdf`
and Textual `3748f499`, with the same updated replay observer and v3 bundle as the
candidate. Control copies are detached cache worktrees. Replay resource spans
record UI-thread CPU, page faults and context switches; GC and heartbeat evidence
are separate. Headless `Pilot.pause` settlement is not input-to-pixel latency.

| Replay | Large Thinking setter / restore | Max GC | Max loop gap |
| --- | ---: | ---: | ---: |
| `toad-live-replay-published-1` | 39.7 / 53.3 ms | 188.9 ms | 271.1 ms |
| `toad-live-replay-constraints-1` | 15.9 / 13.7 ms | 172.5 ms | 283.9 ms |
| `toad-live-replay-filter-batches-1` | 15.0 / 13.3 ms | 205.6 ms | 296.6 ms |

The final replay also includes two three-second loaded-scene spinner intervals,
so its aggregate GC/loop interval is not a matched latency comparison. Each
spinner interval produced 180 compositor updates at requested 60 Hz, with about
6,550 mounted widgets: maximum compositor work 3.40/3.38 ms, maximum heartbeat gap
5.80/5.53 ms, and zero layout/CSS-apply calls. These are headless native compositor
measurements, not terminal/pixel FPS; normal production cadence remains 30 Hz.

Real-terminal all-category receipts still fail acceptance:

| Receipt | Input ack median / p95 / max | Loop max | GC max |
| --- | ---: | ---: | ---: |
| `toad-filter-constraints-1` | 59.4 / 127.1 / 186.5 ms | 132.0 ms | 120.5 ms |
| `toad-filter-worker-batches-1` | 56.1 / 166.5 / 247.3 ms | 200.0 ms | 126.3 ms |

Both completed 72 actions, all seven categories over four threads, and 52/52
unsent input markers. Latest input p99 was 242.7 ms. The latest worst span includes 126.3 ms of GC inside native
`Segment.divide`/compositor paint (125.6 ms thread CPU), with inclusive layout
193.8 ms and compositor 159.2 ms. Those spans overlap and must not be summed.
The previous 34-second replay anomaly was not reproduced or explained; current
large GC pauses are CPU work, not evidence for attributing that old anomaly to swap.

Verification: Textual **3,132 passed, 1 skipped, 4 xfailed** (full except snapshot
tests, 105.76 s); all **49 Toad pilots passed** (164.72 s). Worker admission tests
check chronological matches, unchanged canonical source, actual off-UI selection,
and supersession before publication as well as during either mount.

### Previous published checkpoint

The [tracking plan](ui_responsiveness_plan.md) locks in the four confirmed causes,
viewport-bounded transcript loading/worker filtering, and the spinner/effects
frame budget. Issues: [Textual#4](https://github.com/OpenHCSDev/textual/issues/4),
[Toad#59](https://github.com/OpenHCSDev/toad/issues/59),
[#60](https://github.com/OpenHCSDev/toad/issues/60),
[#61](https://github.com/OpenHCSDev/toad/issues/61),
[#62](https://github.com/OpenHCSDev/toad/issues/62),
[#64](https://github.com/OpenHCSDev/toad/issues/64).
The implementation and [portable debug toolbox](../../tools/performance/README.md)
are being published as linked draft work. **Responsiveness remains unresolved.**
Framework companion: [Textual PR#5](https://github.com/OpenHCSDev/textual/pull/5),
commit3748f4992017be64097e02b8ee531455f7fcd762. The Toad draft now pins that
framework and the core5cb68bb revision used by the isolated correctness suite.

### Required correction to navigation measurements

The first navigation-stage observer replaced two `@on` methods without updating
Textual's decorated-handler registry. Each transcript/ready message then ran its
old decorated handler and the new name-based wrapper. A small dispatch check
reproduced counts1->2; the observer now preserves metadata/registry identity and
asserts exactly one dispatch. This instrumentation affected captures after those
wrappers were introduced, including `toad-priority-interactions-1` and the first
`toad-cold-open-stages-1`. Their absolute navigation/filter load measurements and
the previously quoted740–850ms range are not valid acceptance baselines. Earlier
captures without those wrappers are not invalidated by this particular bug.

Corrected captures are `toad-cold-open-stages-corrected-1`,
`toad-first-frame-control-1`, and `toad-first-frame-gated-1`. A shared SessionView
first-frame gate now releases startup callbacks through their owning message
pumps only after actual presentation/terminal flush. Sidebar refresh and agent
startup cannot accidentally begin inside a paint-suppressed after-refresh phase.
Control/gated median target-mode flush:780.33/690.68ms; ready-handler completion:
814.09/827.11ms. This improves initial feedback in that pair, not overall loading
completion or the50ms goal. Existing cached-sidebar continuity/cancellation tests
and the first-frame lifetime pilot pass.

### All-seven-filter reproduction and repair

Added a720-event fixture with90each user/agent/inbound/outbound/thinking/other and
180tool start/end records. Four-thread pointer stress turns all categories off,
leaves distinct per-thread masks, revisits, and restores using rapid three-click
bursts while typing unsent markers. It exposed a real worker failure after45–52
actions: `_filter_overlay` was cleared by a new filter during an awaited mount,
then the old task called `.mount()` on None.

The fix retains the publication's overlay identity and validates generation after
both container and child mounts; retired work unwinds the old anchor transaction
without advancing cursors or posting coverage. A deterministic failing-before
pilot gates both mount boundaries and verifies typing/other-thread navigation.
Empty masks now suppress pointless history scanning and lookahead. Existing
source-read supersession, in/out semantics and history-anchor pilots pass.

`toad-all-filters-threads-fixed-2` completed72actions and52/52typed characters
(13per thread), restoring all seven categories. Key acknowledgment median69.89,
p95155.94,max204.39ms; a heartbeat gap reached248.62ms. This fixes the crash, not
the frame budget. Some trace spans finish after the original fixed action settle
window; the filter driver now extends each action through verified acknowledgment
instead of silently omitting that work. These scopes must not be mixed in A/B
claims.

### Actual aged-process evidence and replay

User-authorized sampling captured the existing long-running Toad without input
injection/restart. Artifacts remain private and local:

- `toad-live-aged-20260926-1.speedscope.json`:60s/100Hz/GIL+native,5345samples,
  27sampling errors. Native symbols from this interpreter were unreliable;
  use Python-filtered stacks rather than interpreting those symbol names.
- `toad-live-aged-20260926-2-python.speedscope.json`:45s/100Hz/GIL,3868samples,
  zero errors.1555 UI-thread samples; about12% included goal polling. The other
  profile's Python stacks put that overlapping path around18%. Foreground
  service reconstruction/registry decoding is visible, not merely inferred.
- `toad-live-aged-20260926-3-state.pickle` and its JSON metadata:1,352,780bytes,
  13open views, about10,153registered widgets; read-only UI state collection took
  48.69ms, then DTO serialization ran on a thread. Initial export attempts failed
  on runtime geometry and a widget paired with a wire message; those partial
  files are not replay inputs.
- `toad-live-aged-20260926-1-screen.svg`:Textual screenshot export,80.996ms.
  X11 pixel capture failed because the window was unmapped; no focus/move was
  used to obtain it. The original process later exited/restarted, after capture.

The live metadata identifies an exact retention path:
`Footer.__watchers['compact'] -> (subscriber, callback) -> 2,268 closed FooterKey`.
Reactive teardown now unregisters subscriber-owned watches from quiet publishers,
using weak reverse publisher ownership. Four regressions failed before the fix,
including real Footer churn; the focused38-test reactive/data-binding run and
the full framework suite passed afterward.

`replay_state.py` successfully recreated13view slots from the captured data in a
private headless wire/store. This is not a Python-process checkpoint: the v3
projection incompletely captures transient tool/live-input metadata. The replay
contained roughly6,500registered widgets and zero retained closed reactive
subscriptions with the fix. It still exposes large costs: a Thinking filter
setter used185.39ms CPU/wall in one captured thread, with a186.34ms restore.

The display-only class plan now allows root-local style application when parsed
rules prove descendant/inherited/custom styling cannot depend on that marker.
Semantic scope tests pass. The first post-change replay had an extreme34s
wall/1.3sCPU outlier and other timing variation. A later host check showed32GiB
swap fully occupied; attributing the discrepancy is still pending. **No clean
post-change latency win is claimed from that run.**

### Current verification and remaining work

Full Textual suite after reactive lifetime and display-scope changes:
3128passed,1skipped,4xfailed (snapshot directory excluded),115.30s.
The broad Toad suite last passed47cases before the newest display-scope/tooling
checkpoint; focused filter-scope, mount/source supersession and in/out tests also
passed. The packaged runner subsequently passed49cases in170.13s. Scoped Ruff,
CLI help/shell syntax and whitespace checks passed.

The portable toolbox then completed `toad-portable-filters-checkpoint-2`:
72actions, all seven categories restored on four threads,52/52typed markers.
Input acknowledgment median51.61/p95112.56/max217.13ms; action-scoped loop gaps
p9567.06/max177.39ms, GC max144.89ms. This run uses native tab-strip switching,
not the earlier sidebar-revisit mode, and includes acknowledgment in filter
action intervals, so it is not a controlled overall speedup comparison. A first
portable attempt read a stale compositor map immediately after refresh; the
driver now waits boundedly for the current filter projection as well as input
acknowledgment. The remaining217ms input maximum still fails the target.

`benchmark_spinner.py` recorded180headless updates over3s at requested60Hz on a
306x80 minimal scene: median0.737ms/p951.138ms/max2.235ms compositor work, maximum
UI-thread CPU1.198ms, zero layout and stylesheet-apply calls; loop-gap max5.141ms.
This isolates the spinner's steady-state cost. It does not establish delivered
terminal FPS or the same budget under the aged/captured app's other work.

Continue on structural work: bound live/non-tail transcript trees, prepare
filtering on workers, remove unnecessary foreground data reads, verify the
reactive-retention reduction on aged churn, and measure animation frame work.
Spinner render parity/cache coverage exists; sustained60Hz with future effects
has not been demonstrated. Source history and host conditions remain part of
every performance receipt.

The sections below preserve earlier work/history; their "latest" wording is
historical and does not supersede this checkpoint or the corrections above.

## Latest: native resizing and end-to-end navigation, 2026-09-26

The user reports tab switching/opening and sidebar resizing remain very slow.
These are the priority acceptance paths. **The overall issue is not solved.**
The changes remain in the uncommitted test worktrees, not a deployed update to
the user's running application.

### Focused diagnostics and fixes

1. **Hidden goal geometry.** All12 toggles in the initial focused run invoked
   `Conversation.on_resize -> GoalBar.update_document_height -> content_size ->
   compositor.full_map`, despite the goal document being absent. GoalBar now
   skips document measurement without a displayed, expanded goal, and skips
   control measurement when the bar itself is hidden. The new goal-geometry
   regression fails before this change and passes afterward, including outage
   headers, visible goals, collapse and terminal resizing. The unwanted full-map
   rebuild count dropped12->0; this alone did not improve the observed maximum.
2. **Markdown measurement feedback.** An optional layout-request trace showed
   Markdown child-layout outputs repeatedly requesting ancestor remeasurement.
   Textual now exposes `_measured_virtual_size_requires_layout()` with unchanged
   default behavior. PreparedConversationMarkdown declares its arranged-block
   extent to be an output. Authored virtual sizes, watchers and actual scrollbar
   changes retain their normal invalidation. A native-policy geometry oracle
   compares relative descendant regions, virtual extents and scrollbars across
   four widths and content updates. History anchoring and selection pilots pass.
3. **Resize controls incorrectly started text selection.** Real edge dragging
   triggered Screen's selection walker before the handle received MouseDown.
   Event.stop/capture happened too late to prevent that. `SidebarResizeHandle`
   and `SidebarSlider` now declare `ALLOW_SELECT=False`, as the collapse toggle
   already did. The enhanced left/right drag test fails before the change with
   `Resize handle started a text selection`; it passes afterward, including
   slider use, keyboard controls, hover, pointer release and collapse. Ordinary
   conversation selection remains exercised in the full terminal workload.

### Measuring actual user-visible waiting

Heartbeat stalls are not click-to-display latency. The observer now records
navigation preparation/layout/hydration spans and the mode associated with
terminal flushes. The83-action fixture run showed:

- Nine new native tabs: first target-mode terminal flush **738.79–848.21 ms**
  after input dispatch began. Each open performs a pending-screen transition
  followed by the actual session transition. Pending transition durations were
  about119–151ms; actual new-session transitions about350–430ms, followed by
  transcript initialization/rendering. This is a frontend fixed fixture, not
  network/provider latency.
- First return to existing tabs: target-mode flushes mostly67–104ms. Subsequent
  warm returns were commonly39–55ms; later returns after other interactions
  still reached about89ms. Same-mode clicks can flush without a transition and
  are not meaningful tab-switch latency samples.
- A terminal flush is not a physical pixel timestamp or a guarantee that every
  asynchronous content block is ready. Pending/loading feedback is separate
  from the new session's first target-mode flush. These measurements nevertheless
  expose waiting that was missed by quoting loop gaps alone.

Next navigation work must reduce the serial pending/main-screen preparation and
mounting path, not merely bring heartbeat p95 below50ms.

### Unprofiled focused comparisons

Each sidebar comparison below performs12 real pointer toggles at306x80cells:

| Capture (`toad-sidebar-`) | Gap p95 | Gap max | Recorded arrange time | Full-map rebuilds |
| --- | ---: | ---: | ---: | ---: |
| `before-1` | 72.82ms | 89.21ms | 651.80ms | 12 |
| `goal-fixed-1` | 75.93ms | 89.77ms | 627.24ms | 0 |
| `markdown-policy-1` | 63.61ms | 101.40ms | 324.56ms | 0 |
| `markdown-legacy-1` | 72.36ms | 105.40ms | 628.92ms | 0 |
| `markdown-policy-2` | 66.87ms | 79.11ms | 297.92ms | 0 |

The legacy-policy control uses the same sources with an explicit observer-only
override restoring Widget's default measurement policy on prepared Markdown.
The override is recorded in the manifest. Arrangement spans are inclusive and
only recorded at>=3ms, not a sum of all UI CPU. They support reduced repeated
measurement, not a sub50 completion claim; retain the101ms candidate outlier.

New native drag workload: eight drags,16 pointer positions per drag, both sidebars
outward/inward twice, plus reveal/restore toggles. It verifies declared width
changes, unchanged mode/tab roster, and released mouse capture.

| Drag capture | Gap p95 | Gap max | Full-map rebuilds |
| --- | ---: | ---: | ---: |
| `toad-sidebar-drag-before-1` | 105.45ms | 167.94ms | 12 |
| `toad-sidebar-drag-fixed-1` | 82.50ms | 126.13ms | 0 |

Those extra full-map rebuilds all came from selection traversal during dragging.
The remaining resize cost is still substantial layout/render work.

### Expanded full-workload receipt

`toad-priority-interactions-1` completed **83 actions**, including nine opens,
sidebar revisits, eight native resize drags, scrolling, ordinary selection and
filters. Same540-event fixture and Python3.14.2/core5cb68bb environment.

| Interaction | Loop-gap p95 | Loop-gap maximum |
| --- | ---: | ---: |
| Open | 55.39ms | 182.99ms |
| Sidebar tab switch | 35.39ms | 55.55ms |
| Resize | 93.01ms | 112.48ms |
| Toggle | 87.99ms | 141.27ms |
| Selection/scroll | 26.09ms | 49.94ms |
| Filter | 47.66ms | 53.12ms |

Overall p9561.45/max182.99ms; largest GC159.51ms; final census818,956tracked
objects after the additional resizing. This workload differs from the earlier72
actions; do not compare its overall maximum as a controlled global speedup.
The immediately preceding72-action `toad-grind-fixture-goal-markdown-1` had
p9558.05/max201.07ms, GC149.20ms,741,974tracked objects.

### Profiling and correctness

- Memray1.20.0 installed only in `/home/ts/.cache/toad-textual-devtools-314`.
  Captures trace Python allocators/native stacks with aggregated file format.
  Per-action capture begins after geometry snapshots/pointer positioning and
  stops before the next snapshot, avoiding observer-query work in the profile.
- Before/goal-fixed first-toggle captures report peak live allocation1,751,712
  ->1,512,906bytes and still-allocated-at-end1,675,788->1,253,211bytes within their
  tracking windows. These include derived caches; they are not leak totals or
  process RSS. The proven mechanism is removal of full-map geometry work.
- The interpreter lacks native debug symbols. Python allocation stacks remain
  useful; some native frames are unsymbolicated. `memray stats` does not support
  the chosen aggregated format; use FileReader peak/end records instead.
- A whole-interval cProfile probe also included observer snapshots and produced
  suspicious cross-thread caller associations on this runtime. Do not use those
  associations as causal proof. Action-scoped native spans and failing-before
  regressions establish the fixes above.
- Full Textual suite: **3,114 passed,1 skipped,4 xfailed**,102.39s.
- Full Toad pilot wrapper after capture correction: **45 passed**,149.99s.
  An earlier run had44passes plus a goal-resize output-capture timeout after the
  pilot printed success and had exit code0. Persistent descendants can hold pipe
  descriptors open. The wrapper now uses temporary-file stdout/stderr capture,
  preserving the100s process timeout and failure output without waiting for EOF
  from descendants. No pilot is excluded in the45-case run.
- After the two resize-control declarations: drag/slider, pointer-focus, sidebar
  geometry and history-scroll-frame pilots all passed, then the83-action run.
- Scoped Ruff and whitespace checks passed before the final control change;
  final checks are recorded with this continuation.

Useful tools in `/home/ts/.cache`: `compare-sidebar-captures.py`,
`summarize-sidebar-actions.py`, `analyze-layout-causes.py`,
`analyze-focused-toad.py`, `analyze-navigation-stages.py`.
Runner flags: `--sidebar-only --sidebar-cycles 6`, `--resize-only`,
`--resize-sidebars`, `--focused-profile memray` (with the isolated tools directory
appended via TOAD_VALIDATION_EXTRA_PYTHONPATH). Optional layout-cause tracing uses
TOAD_VALIDATION_LAYOUT_CAUSES=1. All profiling modes are diagnostic-only.

## Textual developer console: researched and connected

The user requested higher-leverage debugging and asked about Textual's console.
The [official devtools guide](https://textual.textualize.io/guide/devtools/)
documents `textual console` with `textual run --dev`. The console provides native
event/worker logs, print/Rich output, widget-tree logging and slow-handler
warnings; it is a logging console rather than an interactive heap/CPU profiler.

`textual-dev` was absent from the existing test environment. Version1.8.0 is now
in isolated `/home/ts/.cache/toad-textual-devtools-314`. The official console
service was started on loopback and connected to the candidate source pair
through `TEXTUAL=devtools,debug` and a dedicated port. A real-terminal fixed
fixture run completed17 open/toggle actions with10loaded tabs. Structured state
confirmed `devtools_connected=True`, asyncio debug enabled, and a50ms callback
threshold. Both owned processes were stopped afterward.

Source inspection identified why the console alone is insufficient for the
target: `TEXTUAL_SLOW_THRESHOLD` defaults500ms and clamps to at least100ms.
The message-pump check measures non-Event handler elapsed time, including awaits;
`_callback.invoke` separately warns when callbacks remain pending for3seconds.
These are different from asyncio's per-task-step/handle blocking diagnostics.
The observer now optionally uses `loop.set_debug(True)` and
`loop.slow_callback_duration=.05` with a separate file handler, per the
[Python asyncio debugging guide](https://docs.python.org/3/library/asyncio-dev.html).

The diagnostic produced62 asyncio slow-step warnings, naming screen message
pumps, `screen_update`, `_switch_mode_ready`, and other owners. The native
console captured the widget tree, worker lifecycle, hydration handlers and
mount/unmount/bubbling traffic. Multiple handler lines for one Mount can reflect
normal inherited dispatch, not duplicate mounting. Debug mode and console
serialization add overhead; none of these timings supersede the unprofiled
performance measurements below.

Receipts: `/home/ts/.cache/toad-devtools-diagnostic-1-*`, especially `console.log`,
`asyncio.log` and `state.json`. Reusable runner:
`python3 /home/ts/.cache/run-toad-devtools-diagnostic.py` (timestamped default name).
Only cache-resident diagnostic tooling changed in this investigation.

The next high-leverage investigation is a single slow action correlated across
native event ownership, CPU stacks and allocation stacks. [Memray](https://bloomberg.github.io/memray/overview.html)
supports our CPython3.14/Linux environment and can attribute Python/native
allocations; it has been researched, not yet run. Heap ownership/reference-path
analysis is still needed to explain why large graphs remain reachable.

## Latest allocation/lifetime continuation — 2026-09-26

**The sub-50 ms target remains open.** All changes below are uncommitted in
`/home/ts/wt/toad-navigation-allocation-20260925` and
`/home/ts/wt/textual-render-ancestry-20260925`. The latest unprofiled repeats
completed all 72 actions, with worst loop gaps **173.35 / 198.03 ms**.

### Retained changes since the previous report

- Textual creates optional DOM tree/query/binding/component storage and message
  pump collections lazily, and shares immutable selector type names per class.
  The separate 3,000-node construction/tracemalloc fixture reported
  18,699,392 -> 5,693,408 retained bytes, and 146.98 -> 45.91 ms. Those are
  instrumented construction measurements, not terminal latency.
- Stopped/completed timers release callbacks and completed task contexts.
  Closed screens/compositors release root geometry and pending presentation
  callbacks; closed widgets release derived visual/layout caches. Lifetime
  tests fail on the preceding implementation and pass on the candidate.
- Shared preparation now has a nominal `PreparedValue` storage contract.
  `SerializedWork` opts process-transferable results into retained bytes instead
  of live object graphs. Transcript pages, sidebar/tab projections and reusable
  renderer results declare this policy. Other work keeps worker-side deepcopy.
  Encoding/materialization occurs in workers; scope checks surround delivery.
  Cache byte admission uses the encoded payload plus its wrapper; transcript
  lookahead still checks its materialized page-size limit. Tests verify original
  graph release, independent deliveries, reuse, oversized-result rejection and
  retirement during materialization. This is not a demonstrated latency win by
  itself: the first serialized terminal run was slower at its maximum.
- The message loop publishes only to an already-accessed optional message signal.
  Pumps with no subscribers no longer allocate a weak-key subscriber dictionary.
  It also drops the processed message before waiting for the next one, avoiding
  idle retention of callback arguments or event payloads. Both new regressions
  fail on the earlier framework comparator. The payload test deliberately avoids
  `Pilot.pause()` after delivery, because that helper posts synchronization
  messages that would conceal the old retention.

### Reproducible terminal fixture

Live owner processes began rejecting the newer `Goal.block_reason` schema, after
the previously recorded `mention_source` incompatibility. An updated isolated
client alone cannot repair old live owners. No foreign owner was restarted.

`tests/navigation_terminal_fixture.py` instead supplies fixed read-only native
history responses to the real Toad UI/core wire model and persistent renderer.
It patches `Agent.start` and `Agent.get_transcript_page`; it is **not a live-server
or provider test**. It uses 25 registered threads, 100 wire messages and 540 native
events, paged in groups of 20. The source SHA-256 is:

`c403a324a0cfdc1a203582b23ec06c94cc29838eb26a1cb1a76e275eb8d3fd79`

Each off-screen real-terminal run has nine native opens, 23 sidebar revisits,
20 toggles, ten deep-scroll bursts, two selection gestures and eight filters.
The ordered action sequence and source identity match across the dispose,
serialized, message-lifetime repeats and profile captures. All ten tabs contain
successful fixture views. The Xvfb/st terminal measures 306 x 80 cells.

Normal tests now use Python 3.14.2 and isolated core
`5cb68bb5745813e84bf29ee003bc33ac085fcfe0` from
`/home/ts/.cache/toad-autonomous-5cb68bb-tests-314`. The working project dependency
pins still identify older core/framework revisions; the source pair is required
for this experiment, and pins must be reconciled before publishing.

### Fixed-fixture results

All rows completed 72 actions without py-spy. Heap censuses occur outside the
timed actions and do not force collection. Counts include live and not-yet-
collected objects, not a leak estimate or RSS measurement. GC/layout/render
spans overlap. Heartbeat gaps >=5 ms are not physical pixel latency.

| Capture suffix (`toad-grind-fixture-`) | Gap p95 | Gap max | GC max | Final tracked objects |
| --- | ---: | ---: | ---: | ---: |
| `eager-1` | 57.11 ms | 249.05 ms | 242.80 ms | 930,990 |
| `lazy-2` | 51.90 ms | 189.61 ms | 174.43 ms | 842,523 |
| `timer-1` | 55.10 ms | 222.96 ms | 190.46 ms | 796,675 |
| `dispose-1` | 53.17 ms | 158.19 ms | 148.60 ms | 787,115 |
| `serialized-1` | 50.05 ms | 221.19 ms | 164.21 ms | 771,334 |
| `message-lifetime-1` | 51.51 ms | 173.35 ms | 159.48 ms | 747,717 |
| `message-lifetime-2` | 58.48 ms | 198.03 ms | 169.78 ms | 747,634 |

The eager comparator is `/home/ts/wt/textual-sub50-prelazy-baseline`: base
`ace9226c` plus the already-developed measurement/group/targeted-geometry changes,
not pristine upstream. End-of-run tracked counts are about 20% lower than that
comparison, but neither the best historical run nor this reduction establishes
the sub-50 goal. The second message-lifetime run also includes a small storage
wrapper accounting/slots cleanup; the profile and that final repeat have exactly
matching hashes for 406 Toad and 1,169 Textual source/config files.

Two rejected runtime/mode probes on the fixed fixture:

- Python 3.14.6 (`py3146-1`): p95 60.20 / max 577.94 / GC max 481.26 ms.
  It does not improve this workload; no production interpreter pin changed.
- Existing virtual-channel experimental mode (`virtual-1`): p95 58.16 /
  max 405.54 / GC max 310.59 ms, with 716,880 tracked objects. Smaller object
  count alone did not establish a latency improvement; not enabled by default.

### Current correctness receipt

- Full Textual suite excluding the snapshot directory, `-n 2`:
  **3,113 passed, 1 skipped, 4 xfailed**, 108.38 seconds.
- Toad xdist wrapper: **39 passed**, 148.86 seconds. This includes the new
  serialized-cache delivery/budget regression.
- Sidebar drag/resize pilot, previously excluded due to an exit hang, now
  passed **as a separate cleanly exiting command**, including both sides,
  ANSI/RGB hover, pointer capture, slider mirroring and collapse. One pass does
  not prove the earlier intermittent hang's cause; it is not an unresolved
  failure in this latest run.
- Two-app persistent-renderer integration passed: shared renderer identity,
  Markdown, native diff, file preview, Read selection and owned service shutdown.
- 31 focused framework lifetime/message tests passed; both new message-loop
  regressions failed against the pre-lazy comparator as expected.
- Scoped fatal/unused-import Ruff checks and both `git diff --check` calls pass.

### Remaining bottlenecks and receipts

`profile-1` completed all 72 actions and collected 2,889 GIL-only samples, with
zero sampler errors; 2,825 were on the UI thread. The inclusive Python frame
weights include `_refresh_layout` ~30%, `_render_chops` ~19%, `_arrange_root`
~14%. Frequent leaves include parent/screen/ancestry lookup. These weights
overlap, include native work attributed to Python frames, and are **not a wall
timeline or per-action attribution**. The earlier rejected pass-scoped ancestry
memoization remains removed; this profile alone does not justify restoring it.

The unprofiled final repeat has a 198.03 ms open gap containing 166.32 ms of
UI-thread GC (164.66 ms thread CPU), and a 197.88 ms filter gap containing
169.78 ms GC (168.35 ms CPU). Sidebar toggles also exceed the target **without**
large GC: one 180.69 ms gap contains a 106.86 ms layout/render span, of which
48.97 ms is compositor refresh. Next work must address both retained native
object graphs and foreground geometry/style/render traversal; changing the
collector trigger or inserting heartbeat yields would not establish success.

Artifacts are `/home/ts/.cache/toad-grind-fixture-<suffix>-*`. The runner now
records per-file hashes for dirty sources as well as HEAD/status, avoiding the
previous ambiguity of unchanged HEADs in editable worktrees. Reproduction:

```sh
TOAD_REVISIT_SIDEBAR=1 python3 /home/ts/.cache/run-isolated-toad-workload.py \
  --source /home/ts/wt/toad-navigation-allocation-20260925 \
  --framework /home/ts/wt/textual-render-ancestry-20260925 \
  --environment /home/ts/.cache/toad-autonomous-5cb68bb-tests-314 \
  --name UNIQUE_CAPTURE --display :198 --privileged-display --fixture --census
```

`/home/ts/.cache/check-fixed-fixture-receipts.py` checks input/action identities
and final/profile source hashes. All owned displays were stopped; the only
remaining Xvfb at the final check was foreign PID1114. No commit/PR/merge occurred.

## Earlier pass: explicit sub-50 ms target (not achieved yet)

The user asked to continue autonomously until the stalls are below 50 ms.
Additional changes are implemented in the same uncommitted Toad/Textual trees:

1. **Viewport-based mounted history budget.** Prepared data remains in the
   shared worker cache, but mounted fragments are now budgeted by visible
   fragment count plus admission reserve rather than twice the terminal row
   count. Newly admitted fragments and native selected fragment owners are
   protected from immediate eviction. A selected endpoint can legitimately keep
   more than the nominal mounted budget while it remains selected.
2. **Measured group extents are outputs.** Textual's non-scrolling layout groups
   (`overflow: hidden hidden`, actual containers) commit measured virtual size
   without re-invalidating ancestors for that output. Scrollable/virtual views
   retain their prior feedback. Watches, authored virtual sizes, scrollbar
   changes and genuine mutations still request layout normally. This is narrower
   than the previously rejected suppression of all container feedback.
3. **Targeted anchor geometry.** Viewport compositor reflow can retain declared
   geometry targets and their ancestry paths. SessionView supplies its active
   history anchors, allowing exact compensation without traversing every
   off-screen descendant. Full-layout reference tests compare target regions,
   virtual offsets and rendered strips, including resize, scroll and removed or
   foreign targets. This needs the edited Textual worktree alongside Toad.
4. **User Markdown uses the shared renderer.** UserInput used ordinary
   ConversationMarkdown, which still highlighted user-pasted code on the UI
   thread. It now uses PreparedConversationMarkdown. A gated test fails on the
   old source's UI highlight call and passes on the worker-backed path, retaining
   source/copy and native fence styling.

The mounted-history fixture went from **88 fragments / 443 widgets** to **24 /
123** before selection, while retaining the original 120-event source and
allowing backward paging. Selected offscreen content remains copyable through
further admissions. Existing scroll-frame anchoring, dense/long history, filtered
underfill and inbound reconciliation tests pass.

### Validation

- Full Textual non-snapshot-directory suite with xdist: **3,101 passed, 1 skipped,
  4 xfailed**, 108.37 seconds, on the targeted-geometry/group-commit candidate.
- Broader Toad batch: **37 passed**, one old goal-poll fixture failed because
  current core now requires a genuinely active standby dependency. The fixture
  now declares and retires a test-owned turn (no provider call), and passes
  separately. Sidebar-drag exit remains excluded due to the previously recorded
  teardown timeout; it is not silently counted as a passing command.
- Updated the stale history-prefetch pilot to distinguish background data reads
  from widget admission. It now checks the old page stays unmounted at the tail,
  admission before the visible top edge, and no repeated source read. The old
  assertion that *no background read occurs* also failed on the merged baseline.

### Autonomous runs, all 72 actions completed

All runs use ten tabs, the readiness-verified mixed channel/DM workload and the
loaded main native history. Source history keeps growing; these are not controlled
whole-workload A/B runs. No py-spy was attached and no GC policy was changed.

| Candidate stage | Gap p95 | Gap max | GC max |
| --- | ---: | ---: | ---: |
| Mounted budget | 93.19 ms | 268.59 ms | 227.95 ms |
| + measured groups | 77.70 ms | 207.62 ms | 166.09 ms |
| Python 3.14.6 experiment | 82.63 ms | 460.61 ms | 390.65 ms |
| + targeted anchor geometry (3.14.2) | 73.40 ms | 505.59 ms | 412.54 ms |
| Final incl. user Markdown workers (3.14.2) | **70.98 ms** | **274.23 ms** | **234.99 ms** |

The final run's per-action maxima: opens207.19, ordinary tab switches78.97,
sidebar-row switches240.76, sidebar toggles209.09, deep scrolling274.23,
selection/scroll195.66, filters86.74 ms. Ordinary-switch p95 was41.80 and filter
p95 was32.79 ms, but **neither p95 nor maxima meet the overall sub-50 goal**.
These are loop-wakeup gaps >=5 ms, not physical pixel-frame measurements. The
median excludes shorter ticks. Do not select the best207 ms run and hide later
outliers.

Python 3.14.6 was tested in `/home/ts/.cache/toad-sub50-py3146-tests`, using the
system interpreter and the same core revision. Python's documentation states
generation1/threshold2 were restored in3.14.5:
https://docs.python.org/3.14/library/gc.html . The newer runtime did not eliminate
the large pauses in this workload; no production Python pin was changed.

A further trial kept normal GC enabled throughout scrolling instead of Toad's
existing pause-on-scroll behavior (`toad-sub50-normal-gc-1`). It completed72
actions with p9566.95 ms, max497.33 ms and GC max201.84 ms, again with changed
live source contents. It did not resolve the worst pauses, so that policy
experiment was reverted. The retained candidate leaves the existing GC policy
unchanged; there is no freeze, manual-collection scheduling or disabled-GC
shortcut to manufacture a sub-50 result.

Latest receipts: `/home/ts/.cache/toad-sub50-{budget-1,group-commit-1,py3146-1,targeted-anchor-1,final-candidate}-*`.
The final run initially hit Xvfb startup readiness before any actions. The runner
now polls the actual display endpoint instead of sleeping a fixed700 ms; the
retry completed. All owned displays were closed.

Remaining constraints: whole-process collection pauses, native widget/style
allocation, and large sidebar/layout bursts. Reducing those requires further
work; these changes are not a sub-50 completion claim or a merged checkpoint.

## Autonomous validation follow-up

The user explicitly requested unattended off-screen testing rather than asking
them to exercise the manual preview. The existing automated workload was run
repeatedly with both candidate worktrees, without modifying their production
source underneath the running manual preview.

### Environment and test-readiness findings

1. The machine's `/tmp` write limit prevented Xvfb from writing its PID lock.
   Diagnostic scripts moved to `/home/ts/.cache`. The isolated runner now keeps
   server/terminal logs, checks the selected display is unused, and supports a
   `--privileged-display` mode. Only the owned Xvfb server uses that privilege;
   Toad, its backend client and input driver run as the ordinary user. Each owned
   server is stopped afterward. No desktop input was sent.
2. The old test backend `e2fd9d8` stopped reading the live registry when another
   process began writing `Goal.mention_source`. A separate test environment was
   created with current core `49553ba70dc8bd1c67464ade8735d21921d74379`.
   Production environments were not upgraded or restarted.
3. **A tab-count check was insufficient.** Some new native-thread views showed
   attachment errors from old live owner processes, even with the updated test
   client. The driver now checks loaded/initialized content and absence of error
   blocks after every open. A strict native-thread run reproducibly fails on
   `Goal.__init__() got an unexpected keyword argument 'mention_source'` returned
   by an existing owner. Its error UI is not a successful cold-thread-load test.

Earlier `toad-autonomous-current-full-{1,2}` files completed their actions but
lacked this readiness gate; they are **not** evidence that nine native histories
loaded. The first old-backend run completed 72 actions; the second was interrupted
after 55 by the schema mismatch. Their timings are retained only as diagnostics.

### Two readiness-verified mixed runs

`toad-autonomous-mixed-verified-{1,2}` each completed **72 actions**, with the same
ten-tab composition and 306×80 terminal geometry:

- Four channel views (`#any`, `#openhcs`, `#nra`, `#comms`), five DM views, and the
  already-attached main thread's native history.
- All nine opened views reported initialized history and no error blocks.
  Three channels each loaded 48 messages; the other channel and five DMs were
  valid empty histories. This is not ten populated native transcript tabs.
- Twenty sidebar toggles, nine opens, 23 revisits, ten deep-scroll bursts,
  two selection/scroll gestures and eight category-filter changes.
- Channel/DM source fingerprints matched between runs. Main-history starting
  and ending page fingerprints/offsets matched; its first retained page moved
  from byte offset 109,873,901 to 109,501,062. The number of retained fragments
  at the end differed (104 versus 98), so full transient widget states were not
  identical. Filters and sidebar preferences returned to their initial values.

| Loop wakeup gap measurement | Run 1 | Run 2 |
| --- | ---: | ---: |
| Overall p95 (gaps >=5 ms) | 126.04 ms | 131.29 ms |
| Overall maximum | **358.58 ms** | **449.19 ms** |
| Ordinary tab revisit maximum | 34.30 ms | 44.76 ms |
| Deep-scroll maximum | 299.35 ms | 335.06 ms |
| Selection + scrolling maximum | 351.57 ms | 255.82 ms |
| Filter maximum | 101.44 ms | 119.43 ms |

These are instrumented loop gaps, not physical terminal-pixel latency. No py-spy
was attached. The repeatable remaining costs are layout/render/anchor work and
GC during deep history, selection and sidebar changes. There is no all-clear
claim for responsiveness.

A baseline run with the same updated core and mixed action sequence also completed
72 actions (maximum496.16 ms), but the main transcript grew before that run and
its paging fingerprints changed. It is **not a controlled speedup comparison**.
Two preceding readiness-verified DM-only runs completed 73 actions each, but are
also kept separate from this mixed-view pair.

With current core `49553ba`, ten targeted pilots passed under xdist, covering
owner-reader reuse, shared preparation/delivery, history lookahead/anchors,
category filters, prepared bars, current delivery, inbound reconciliation and
pointer focus. Existing native-owner processes remain an external compatibility
blocker for fresh native-thread attachment testing; they were not restarted as
part of this UI validation.

### Current autonomous tooling and receipts

Scripts now live at:

- `/home/ts/.cache/run-isolated-toad-workload.py`
- `/home/ts/.cache/toad-expanded-live-stress.py`
- `/home/ts/.cache/sidebar_validation_driver.py`
- `/home/ts/.cache/run_sidebar_validation.py`
- `/home/ts/.cache/summarize-autonomous-tests.py`

The launcher remains `/home/ts/.cache/toad-history-validation-launch.sh` and now
imports the diagnostic driver from the cache directory. Important flags:
`--wire-views` chooses channel/DM views with readiness assertions; `--open-only`
isolates attachment checks; `--privileged-display` handles the current tmpfs
limitation. Only verified observer processes accept diagnostic signals.

Test environment: `/home/ts/.cache/toad-autonomous-49553ba-tests-314`.
Receipts under `/home/ts/.cache/`:
`toad-autonomous-mixed-verified-{1,2}-*`, `toad-autonomous-mixed-baseline-*`,
`toad-autonomous-native-readiness-gate-*`, and `toad-autonomous-wire-full-{1,2}-*`.
The older `current-full`/`readiness` files must not be presented as native-history
load passes. Raw screenshots/source snapshots stay local.

Correction to the manual-preview description: checking worktree HEADs does not
freeze uncommitted files. That preview runs directly from the working sources;
its production source was deliberately left untouched during these tests.

## State and reproduction boundary

- Editable Toad: `/home/ts/wt/toad-navigation-allocation-20260925`, branch
  `perf/navigation-allocation-20260925`, based on main `01f4cfe` (through PR #54).
- Editable Textual: `/home/ts/wt/textual-render-ancestry-20260925`, branch
  `perf/render-ancestry-20260925`, based on merged main `ace9226c`.
  Despite its experimental branch name, its retained change is only measurement
  cache lifetime; the ancestry-cache experiment was removed.
- Isolated backend: `/home/ts/.cache/toad-allocation-tests-314`, core pinned to
  `e2fd9d8b70524bfa500d97c120a7404ad13bdd64`, matching this Toad base.
- Baseline snapshot: `/home/ts/wt/toad-allocation-baseline-01f4cfe`.
- All UI automation used owned off-screen Xvfb terminals. The user's desktop
  input and running windows were not targeted. Test viewers/displays were closed.
- This work is **uncommitted/unpublished**. It does not change the prior merged
  PRs or the installed shared stack. Do not install into another agent's stack.

## Retained changes

### 1. Cache bar work by its actual presentation inputs

`ThreadRowsWork` previously hashed and retained entire `ThreadView` records.
Timestamp/authority-only changes invalidated the same displayed output, and
delivery copied those full records into every retained native row.

`ThreadRowInput.presentation()` now projects the exact label, summary, busy state,
model, identity, unread, pin and pending-action inputs on the worker. The shared
work identity and prepared result use that compact immutable declaration. Native
navigation still uses the owning sidebar's authoritative model. The row no
longer keeps a second full core record solely for spinner updates.

Fixed 60-row/16-poll fixture, changing only last-seen timestamps:

| Work-result boundary | Before | After |
| --- | ---: | ---: |
| Executions / hits | 16 / 0 | 1 / 15 |
| Accounted retained result bytes | 1,858,368 | 76,536 |
| Median delivery time | 8.25 ms | 4.41 ms |

These are preparation/delivery times, **not UI-frame latency**. Tests also verify
unread, pin and pending-action changes still change output, and both bar types
continue using the shared runtime.

### 2. Drop measurements whose revision can never be reused

Textual's box-model cache retained up to sixteen combinations including old
layout/style revisions. Generation keys prevent stale hits, but retaining an
obsolete result still retains its graph for garbage collection to traverse.

The cache now clears its old partition when measurement enters a new revision.
It retains ordinary width/viewport/fraction variants within the current revision.
No genuine invalidation or measurement feedback is suppressed. Deterministic
tests fail on baseline and pass with the change, including child-driven ancestor
size updates and same-revision measurement identity reuse.

Alternating **baseline/candidate/candidate/baseline** runs of the same many-tab
fixture, 40 peers and 12 channels, identical final 2,789-widget tree:

| Metric | Baseline runs | Candidate runs |
| --- | ---: | ---: |
| Obsolete measurements retained | 2,773 / 2,763 | 59 / 59 |
| First reverse-return completion median | 90.06 / 86.62 ms | 82.43 / 82.21 ms |
| First headless display median | 71.60 / 66.03 ms | 64.31 / 61.38 ms |
| Warm reverse-return completion median | 24.23 / 20.42 ms | 25.75 / 25.40 ms |

The retention reduction is repeatable. First-return timing improved modestly;
warm-return timing did **not** improve. This is headless display/completion, not
terminal pixels. One candidate warm pass had an extra real reflow; the tests
preserve that invalidation instead of hiding it.

An off-screen live census before the change counted 9,687 obsolete and 10,586
current measurement entries after eleven tabs. Final candidates counted only
239/214 obsolete entries and 10,174/11,324 current ones. Inactive invalidated
widgets can retain their last partition until measured again. Live content and
mount counts vary; do not treat these as identical full-heap comparisons.

### 3. Reuse the coordination reader for owner RPC preparation

A structured trace caught `wire(...)` construction and registry JSON decoding on
the UI thread during tab opening. `_owner_request` constructed one service itself,
then `RuntimeProxy` constructed another because the UI agent did not expose its
own service through the proxy's binding contract. Repeated goal/delivery polling
therefore reparsed the registry despite an existing shared reader. One observed
constructor triggered a 213 ms UI-thread GC pause.

Owner lookup and proxy construction now run off-thread. The agent reuses the
same revision-aware coordination service as its transcript reader. A nominal
`OwnerRequestContext` supplies that captured service to the core proxy, without
capturing a UI widget or replacing authoritative routing. The proxy still checks
the live owner before sending. Root/thread changes during preparation reject
the obsolete request; actual RPC results are not cached. Proxy cleanup is explicit.

Fixed fixture: 100 registered threads, 20 status polls, real service/proxy
construction with immediate fixture transport replies; Toad imports are warmed
equally before timing:

| Preparation measurement | Before | After |
| --- | ---: | ---: |
| Service constructions | 40 | 1 |
| UI-thread constructions | 40 | 0 |
| Median request preparation | 4.003 ms | 0.176 ms |
| Maximum request preparation | 5.376 ms | 4.833 ms |
| Total UI-thread CPU | 76.334 ms | 1.876 ms |

This isolates avoidable preparation, excluding socket/server latency. A separate
gated regression verifies concurrent reuse, off-loop construction, root changes
and refusal to send when identity changes. It fails on the frozen baseline.
The existing transcript reader-reuse and real-owner goal/delivery tests pass.

## Real-server off-screen evidence

All runs used 306×80 cells / 2149×1620 pixels, ordinary terminal input and no
py-spy. Instrumentation measured loop wakeups (only gaps >=5 ms), native layout,
render calls, GC CPU/wall duration, preparation and page fingerprints. These are
not complete terminal-pixel latency measurements. Inclusive spans overlap.

Baseline main navigation-only run: 45 actions, max gap **337.45 ms**, p95
**111.90 ms**, GC max **305.48 ms**. Thread opens max337.45, channel-open max324.39,
tab switches max242.87 ms.

Final owner-reader + compact-bar + measurement candidates:

| Observation | Run 1 | Run 2 |
| --- | ---: | ---: |
| Completed actions | 45 | 48 |
| Overall loop-gap p95 | 88.59 ms | 83.28 ms |
| Overall loop-gap max | 234.34 ms | 257.10 ms |
| Thread-open max | 217.78 ms | 257.10 ms |
| Channel-open max | 133.72 ms | 84.62 ms |
| GC max | 213.35 ms | 191.37 ms |

These final runs are promising but **not a controlled overall speedup claim**:
live inputs changed, and the driver now prefers an already-visible sidebar row
for native tab revisits to avoid racing an auto-scrolling header. The earlier
framework-only candidate reached 552.01 ms with 12 tabs, while a full 73-action
candidate before the owner-reader correction reached 345.83 ms (GC329.81).
All those results are retained locally. The final fix is not proof that deep
history, every large roster or worst-case navigation meets 16 ms.

## Validation

- Textual full non-snapshot-directory suite, xdist `-n 2`: **3,098 passed,
  1 skipped, 4 xfailed**, 104.78 seconds.
- Initial Toad batch: **28 passed**; a missing external fixture path and a
  sidebar-drag exit timeout were reported. Delivery passed with the corrected
  fixture path. Sidebar drag printed success but again timed out during exit;
  it is not a clean-command pass.
- After owner-reader changes: **11 targeted Toad pilots passed with xdist**,
  including goal server polling, owner edits, delivery, inbound reconciliation,
  pending tabs, prepared bars and worker history. Transcript reader-reuse passed
  separately. No broad typing-clean claim is made.

## Rejected / diagnostic experiments

- A synchronous pass-scoped DOM ancestry cache passed semantic tests but did not
  provide a convincing benefit in four alternating sidebar runs. It was removed
  completely from the framework worktree, including its tests.
- Existing `TOAD_BENCH_VIRTUAL_CHANNELS=1` mode was tested read-only as an
  allocation probe: 43 completed actions, max272.03 ms, ~1.07M tracked objects
  after eleven tabs versus baseline ~1.26M. Contents and navigation paths varied;
  the mode is still experimental and was **not** enabled by default.
- One cache-lifetime live attempt failed on stale test-driver tab targeting after
  20 actions. It is excluded from complete-workload claims. Driver changes prefer
  exposed native sidebar targets and check for disappeared tabs.

## Commands and artifacts

Use the same pinned source paths for worker subprocesses. Run correctness suites
with xdist; run performance comparisons serially.

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/ts/wt/toad-navigation-allocation-20260925/src:/home/ts/wt/textual-render-ancestry-20260925/src:/home/ts/.cache/toad-allocation-tests-314/lib/python3.14/site-packages:/home/ts/.agent-comms/stack/.venv/lib/python3.14/site-packages \
TMPDIR=/home/ts/.cache \
/home/ts/.cache/toad-allocation-tests-314/bin/python tests/owner_reader_reuse_pilot.py
```

Key local artifacts:

- `/home/ts/.cache/toad-allocation-{baseline,compact-rows,virtual-probe,revision-cache-2,full-candidate,reader-candidate,reader-candidate-2}-*`
- `/home/ts/.cache/toad-measurement-{1-baseline,2-candidate,3-candidate,4-baseline}.json`
- `/home/ts/.cache/toad-ancestry-fixture-pairs.json` (rejected experiment)
- `/tmp/opencode/run-isolated-toad-workload.py`, `compare-lifetime-runs.py`,
  `compare-measurement-revisions.py`, `summarize-measurement-census.py`

New test/measurement entry points: `bar_projection_reuse_pilot.py`,
`navigation_allocation_pilot.py`, `owner_reader_reuse_pilot.py`,
`owner_poll_latency_pilot.py`; framework `tests/test_box_model_cache_lifetime.py`.

Next priorities: avoid constructing full transient sidebar trees when opening a
native tab; reduce stylesheet/mount allocation during paging; preserve native
focus, selection/copy, owner identity and read boundaries. GC remains enabled
under the existing application policy; no manual collections/freezing were used
to manufacture performance results.
