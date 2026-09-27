# UI responsiveness tracking plan

Status: **draft implementation and investigation; performance targets unmet**.
The branch includes the current Toad implementation, regression pilots, audit,
and the [debug/capture/replay toolbox](../../tools/performance/README.md).
Textual changes are tracked in [companion draft PR #5](https://github.com/OpenHCSDev/textual/pull/5).
The dependency pin includes framework checkpoint
`4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e` (merged Textual PR5: retired-scene ownership, native
presentation reuse, declaration-bound dispatch and nonblocking removal completion).

## Locked-in issues

The four confirmed causes:

1. [Textual #4](https://github.com/OpenHCSDev/textual/issues/4): long-lived reactive
   publishers retain retired subscriber widgets/callbacks. The aged live capture
   contained2,268 closed FooterKey subscriptions on Footer.compact.
2. [Toad #59](https://github.com/OpenHCSDev/toad/issues/59): synchronous filter
   invalidation traverses message descendant trees for a display-only change.
   A captured-data Thinking setter used about185ms of UI-thread CPU.
3. [Toad #60](https://github.com/OpenHCSDev/toad/issues/60): owner/goal polling
   reconstructs coordination services and loads/decodes registry data on the UI
   thread. Two live profiles show this as a substantial foreground path.
4. [Toad #62](https://github.com/OpenHCSDev/toad/issues/62): filter supersession
   during awaited mounts can crash or publish stale rows/cursors.

Additional requirements are first-class work items:

5. [Toad #61](https://github.com/OpenHCSDev/toad/issues/61): unload transcript
   widget trees far outside the viewport and lazily reload canonical history;
   prepare filtered data/views on workers. Source size must not dictate
   steady-state UI cost. Include non-tail and inactive-tab live accumulation.
6. [Toad #64](https://github.com/OpenHCSDev/toad/issues/64): paint-only thinking
   spinners and a high-frame-rate foundation for future effects.

## Budgets and acceptance

- Target 16.7 ms steady-state frame work for 60 Hz animation. Current throbber cadence
  is 30 Hz; timing its renderer is not proof of delivered 60 FPS.
- End-to-end interaction target is under50ms, including typing, filtering,
  opening, switching and resize. Meeting the median alone is insufficient.
- 200 ms UI-thread stops are failures, regardless of whether a test eventually
  completes. Report p50/p95/p99/max and input acknowledgment, not only averages.
- Loading and spinner feedback are allowed; typing, navigation and cancellation
  must remain available while slower work completes.
- Measure cold-open loading feedback, target-mode terminal flush, content-ready
  completion and warm switching separately.
- Scale transcript source size10x/100x while bounding mounted widgets and cached
  bytes. Preserve anchors, selection/copy, live arrivals and visible-only reads.
- Exercise all seven filters across multiple threads, all-off/restore, rapid
  toggles, blocked reads/mounts, closing and switching, and unsent draft typing.

## Current implementation progress

### Toad

- Compact worker identities/results for sidebar projections and shared
  serialized preparation storage with independent worker-delivered values.
- Reuse coordination readers and move cold owner lookup/construction off-loop.
- Viewport-based mounted history budgets, selected/anchor protection, and
  targeted viewport geometry through the Textual companion.
- Worker-prepared user Markdown; Markdown declares measured child extents as
  output rather than triggering redundant ancestor measurement.
- Hidden/absent goal documents avoid forcing full-tree geometry on resize.
- Resize handles/sliders opt out of accidental text selection and its full-tree
  traversal during pointer capture.
- A shared first-presented-frame startup boundary for session views, sidebar
  source refresh and conversation startup. Close/cancel checks preserve ownership.
- Filter publication retains its own overlay and rechecks generation after
  awaited mounts; stale work cannot advance the new filter cursor. Empty masks
  stop pointless older-history scans and lookahead.
- Category filtering uses a model-owned display constraint, preserving authored
  CSS without rematching ordinary message subtrees. Custom marker selectors keep
  their ordinary styling path through a parsed-declaration dependency check.
- Filtered-history selection executes through shared `PreparationRuntime` model
  workers. Only four matching fragments are admitted per batch; a data-only source
  cursor retains the unadmitted part of the current page. Superseded preparation
  and mount results cannot publish or advance the replacement filter's cursor.

### Textual companion

- Retire obsolete box-model cache generations; targeted anchor geometry for
  viewport layout; measured-extent policy distinguishing layout outputs from
  authored inputs, including scrolling child containers.
- Lazy optional DOM/message storage, shared immutable selector metadata.
- Timer callback/task cleanup and closed presentation/cache cleanup.
- Avoid unused message signals and idle retention of processed payloads.
- Subscriber-owned reactive cleanup with weak publisher tracking.
- Parsed-declaration query for local display-only class invalidation.
- Composable model display constraints and parsed class-reference lookup.

## Evidence and limitations

### Current-main integration for landing

Textual PR5 is merged at `4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e`; its tree
matches the verified framework candidate. Toad's integration preserves current
main's canonical route validation, private-history and exact-ID queue boundaries,
MCP interfaces, maintenance admission and current core pin. Async ACP validation
passes the original wire session identity to those handlers. Reader sharing uses
the route-owned cached service only when its root matches the trusted attachment.

The pilot runner now includes78provider-free cases, adding22current-main contracts.
The existing queue/private-cursor unit suites add30cases plus73subtests. Final
current-main `52db1eb` / core `b1e5bfd` validation passed107cases plus73subtests
in288.13s; the remaining large comms pilot passed serially in79.86s. Old partial-Agent fixtures
now construct real Agents, lifecycle fixtures carry source identity/sequence,
remote failure notices leave drafts untouched, and the cancellation fixture drains
remaining thread work before deleting its wire. The100s per-pilot deadline remains
unchanged. Main's exact-byte
queue producer check was updated only after the documented source comparison in
[the queue contract](../exact-id-queue-view.md).

The integrated72-action native filter fixture preserved52/52typed markers, all
masks and drafts. `toad-pr65-main-integration-filters-1`: input median37.48/
p9569.93/max79.95ms; loopmax127.50ms; GCmax74.50ms. These are new-core integration
receipts, not a controlled comparison against the earlier dependency environment.
The remaining latency targets continue in a fresh follow-up after landing.

After main's final core/history-wording update, the full native ten-tab workload
`toad-pr65-final-integration-navigation-1` completed83actions including eight resize
drags. Loading feedback median64.27/max95.86ms; final session-shell median215.43/
max345.19ms; switching median68.80/max134.19ms; ready-handler median724.41/
max914.41ms. Loopmax121.05ms and GCmax111.69ms remain above the performance target.
This confirms integrated workflow operation, not sub50ms acceptance.

### Owned removal completion and direct input ingress

Key-route diagnostics found input waiting behind unrelated native widget removal:
one key was queued at5ms but did not dispatch until91ms. The framework no longer
awaits incomplete removals in the app's message queue. `AwaitRemove` owns a shared
completion, publishes once, shields teardown from cancelled observers and releases
retired widget ownership on completion. Self-removal and exception propagation
retain their native contracts. The driver also queues `post_message` directly on
the owning loop, eliminating a redundant coroutine/Future relay before ingress.

Seven removal tests include four failing-before regressions; two driver tests
cover callback ordering and priority bindings/focus/paste. Full verification:
**3,440 framework tests passed,1skipped,4xfailed**, **56 Toad pilots passed**.
The spinner pilot now settles the setup reconciliation frame before measuring
paint-only animation; its no-layout assertion remains. A prune snapshot passes.

All native captures below completed72actions/52markers with masks/drafts intact:

| Capture | Input median / p95 / maximum (ms) | Loop maximum (ms) | GC maximum (ms) |
| --- | --- | --- | --- |
| `toad-reactive-access-filters-1` (published control) |42.63 /95.47 /143.68|106.76|59.66|
| `toad-removal-completion-filters-1` |37.68 /68.81 /73.07|117.12|64.90|
| `toad-owned-removal-ingress-filters-1` |24.56 /54.36 /93.90|121.48|62.57|
| `toad-owned-removal-ingress-filters-2` |29.42 /49.04 /59.98|103.23|62.15|

The final two runs use identical runtime code, run serially without profilers or
the extra key-route probe. The93.90ms input tail overlapped a58.36ms UI-thread
collection. Do not discard it in favor of the59.98ms repeat. Maximum loop stutter
is still above100ms, dominated by sidebar layout+paint and occasional GC; the
universal sub50ms goal remains open. Anchor recapture also sometimes forces a
redundant full geometry pass, visible in the remaining slow-key traces.

Diagnostic-only `toad-input-route-control-1` and `toad-removal-input-route-1`
record queue/dispatch timestamps (max125.23/79.83ms). Use
`analyze_trace.py PREFIX --slowest-inputs 3` to inspect overlaps and frames; these
inclusive spans must not be added together.

### Declaration-bound reactive access checkpoint

Post-reboot profiling isolated the `hasattr` hot path:34,074 of38,255 calls in a
sidebar action came from `Reactive.__get__`, repeatedly discovering initialization
and compute capability. The framework now resolves stored/computed access from
concrete-class declarations and directly dispatches through that contract. It
preserves lazy defaults, watcher/validator behavior, read-only computed values and
ordinary method overrides. A reproduced private-compute inheritance bug is fixed.
Target-only CSS queries also dispatch through `SelectorSet` without constructing
unnecessary ancestry paths; relational selectors keep their existing interpreter.

Current full receipts: **3,431 framework tests passed,1skipped,4xfailed** (excluding
snapshots), **56 Toad pilots passed**. In the corresponding focused profile,
reactive reads made zero `hasattr` calls; total calls fell to1,972. Roughly11.4k
reactive reads used about8ms cumulative profiled time versus36ms previously.
Profiler overhead and overlapping call times prevent treating this as a wall-time
or end-to-end speedup claim.

Post-reboot unprofiled controls/candidates, each72actions/52typed markers with all
seven filters and drafts preserved:

| Capture | Input median / p95 / maximum (ms) | Loop maximum (ms) | GC maximum (ms) |
| --- | --- | --- | --- |
| `toad-post-reboot-checkpoint-control-1` |39.43 /81.53 /95.88|127.56|55.00|
| `toad-target-selector-filters-1` |43.81 /86.45 /102.24|107.61|67.25|
| `toad-reactive-access-filters-1` |42.63 /95.47 /143.68|106.76|59.66|

The dispatch optimization is verified, but these runs do **not** establish an
end-to-end latency improvement. The universal sub50ms target remains open, with
sidebar layout+paint still reaching about100ms even without a major collection.
The reboot removed the temporary renderer-dependency environment; it was restored
in a durable isolated cache environment using declared `zmqruntime==0.2.24`.
Post-reboot controls use that same environment; pre-reboot timings are historical.

### Committed off-tail retirement checkpoint

Live presentation now declares its source-coverage contract through
`CommitParticipant`: settled source-owned blocks use a captured-cohort claim;
incoming wire notices require exact persisted sequence IDs; local interactive
sessions declare a checkpoint barrier. Unrelated local widgets are retained.
`CheckpointPlan` supplies follow-tail or retained-viewport behavior, keeping the
coordinator independent of concrete message widget types.

With an existing idle canonical history, off-tail commits extend its readable
frontier and retire covered offscreen live blocks without replacing current pages
or mounting unread bodies. Visible, selected, focused and cursor-owned blocks are
protected. Source identity, cursor progression, scroll intent and lifetime are
rechecked across awaits. Inactive tabs can retire without waiting for a paint frame.
This path neither reanchors the reader nor acknowledges the newly saved frontier.

A newly reproduced race is also fixed: provisional replacement pagers previously
announced coverage during mounting, before their acceptance check. An incoming
notice could disappear even when cancellation or reader movement then rejected
the replacement. Provisional pagers now acquire coverage ownership only after
acceptance; cancelled/superseded mounts are rolled back. Accepted source access
survives cancellation once live retirement has begun.

Verification: **56 pilots passed in298.31s**. The new off-tail fixture retires432
live blocks over12commit cycles with at most3outer widgets, retaining the exact
history/page/fragment objects and the painted marker position on every observed
frame. It also tests selection/focus, local barriers, exact/missing incoming IDs,
concurrent arrivals and scrolling, exposed block protection, invalid progress,
source replacement/rewind, inactive tabs, drafts, read acknowledgment and later
source access. The inbound pilot covers failing-before provisional publication,
cancelled/superseded mounts and eventual retirement of released selected notices.

Unprofiled `toad-off-tail-checkpoint-filters-1` completed72actions/52typed markers
with all masks and drafts restored. Input median57.70/p95122.55/p99131.55/
maximum135.50ms; loop maximum173.42ms; GC maximum116.31ms. The largest collection
used113.39ms of UI-thread CPU and overlapped the largest loop gap. The universal
sub50ms target remains unmet; this is a retention/correctness result, not a claimed
latency win. A subsequent55sGIL-only profile (`toad-off-tail-checkpoint-profile-2`)
recorded2121samples/0errors, with overlapping main-thread shares of31.38% reflow,
19.39% paint and16.19% box-model resolution. Sampling shares are not wall timings.

All receipts above precede a user-initiated reboot. One profiling launch failed its
30s readiness deadline before the successful retry; at that time host load was
high and swap full, without established causality. Post-reboot work must reverify
process ownership and obtain a fresh control. Off-tail bootstrap without an
existing history, arbitrary protected spans and other local shell growth remain
open. Textual sources are unchanged in this follow-up.

### Shared projected paging checkpoint

Filtered older history previously appended every accepted fragment to a separate
container. Batch size limited each insertion but did not bound retained widgets.
It now uses the ordinary pager through polymorphic source/projection contracts:

- `PreparedPageSource` owns prepared reads, prefetch and retirement.
- `TranscriptPageProjection` owns selection; `CategoryProjection` runs that work
  on the existing model lane.
- `ProjectedTranscriptSource` retains one canonical boundary prefix and reads
  earlier records through the existing bounded source cache. Empty matching spans
  advance native cursors without creating empty widget pages. Reverse reads stop
  at the retained prefix, preventing overlap with the canonical mounted tail.
- `ProjectedTranscriptHistory` reuses ordinary admission, eviction, anchoring,
  focus/selection protection and cursor controls. The parent bootstraps it; the
  child then owns edge scheduling. There is no second append-only renderer or
  competing parent scanner driving the same window.
- `PresentationBudget` centralizes validated item, admission, reserve and widget
  budgets. Defaults are configurable heuristics; visible/protected content may
  exceed the nominal item budget. Source data is not deleted to meet a UI limit.
- Native page transactions take a local widget lock rather than holding the
  app-wide paint mask across mount awaits. Anchor transactions do not start a
  frame wait after their screen has become inactive.

Scaling fixture results (budget6items, admission2, no reserve batches):

| Source records | Matching records visited | Peak mounted fragments | Peak page widgets | Peak descendant widgets |
| ---: | ---: | ---: | ---: | ---: |
|80|3|3|3|15|
|800|26|10|9|40|
|8000|258|10|9|40|
|8000, no matches|0|0|2|4|

Every matching record was visited backwards and forwards without duplication;
selected native text survived paging; restoring all categories retained the
original canonical page object. The counts were observed before the final local-
transaction/scheduler refinements; the same bound and coverage assertions pass
against the final candidate. Protected selection spans can extend the working
set and are not claimed to have an absolute source-independent bound.

Final full pilot run: **55 passed in290.69s**. This includes new projected-history
scaling, sparse/underfilled filtering, late mounted-batch supersession, typing and
tab switches while admission is held, and suspension inside an anchor mutation.
One earlier full invocation hit its outer240s tool timeout after54cases; the
completed run used a larger outer timeout without changing per-pilot limits.

Native four-thread/all-seven-filter capture `toad-projected-window-filters-3`
completed72actions and52/52typed markers, with all masks/drafts restored. Input
median55.62/p95112.16/max131.61ms; loopmax173.08ms; GCmax109.06ms. Earlier candidate
captures `toad-projected-window-filters-1` and `-2` are retained, including the
200.12ms input outlier in `-2`. This establishes bounded filtered presentation and
correctness, **not** an end-to-end latency win or the universal sub50ms target.
The Textual worktree is unchanged in this follow-up.

### Async tab activation and polymorphic target dispatch

New tabs now present a loading shell before route discovery, sidebar population,
conversation mounting or agent/history startup. Sidebar hydration and retirement
run after the activation's presented-frame receipt. They no longer hold the
navigation transaction or a global paint mask across preparation/mount awaits.
Closing/superseding a view invalidates delayed publication and frame receipts.

`NavigationTarget` owns target behavior through SessionTarget, ThreadTarget,
ChannelTarget, DirectTarget and FeedTarget. `NavigationOwner` supplies each view's
`NavigationContext`; native and virtual rows share this dispatch. Serialized
kind strings are decoded at one registry boundary rather than compared across
views. Existing history readers still resolve canonical identity off-loop.

`PendingTabShells` owns bounded UI-only lookahead; it performs no route discovery
or sidebar-source work. `ToadApp.PREPARED_TAB_SHELLS` is configurable (default1,
zero disables lookahead), validated, and released on shutdown. Prepared shells
bind to one requested route before their first presentation.

Matched83-action ten-tab native workloads (including eight resize drags):

| Measurement | Previous median / maximum (ms) | Async candidate median / maximum (ms) |
| --- | --- | --- |
| Opening loading-frame flush |267.14 /322.57|53.52 /62.59|
| Final session-shell flush |696.19 /957.23|311.30 /345.64|
| Switching target-frame flush |169.34 /204.15|55.09 /105.18|
| Agent-ready handler completion |831.72 /1093.16|819.74 /881.51|

Loading feedback and fully loaded content are intentionally measured separately.
The previous loading-frame metric was recomputed from its original trace using
the same analyzer. A smaller three-open candidate recorded44.49–51.33ms loading
feedback; the larger workload above remains the stronger receipt. The universal
sub50ms target is **still not met**. The candidate's loop maximum was187.28ms
with132.89ms GC; async loading does not remove those unrelated stalls.

All-seven-filter/four-thread stress completed72actions/52typed markers with every
mask and draft retained: input median44.67/p95101.35/max130.12ms. Private prefixes:
`toad-prepared-polymorphic-navigation-6`, `toad-prepared-polymorphic-filters-7`;
control `toad-current-structural-navigation-1`. Earlier intermediate prefixes
`toad-async-activation-open-1`, `toad-async-shell-open-2`,
`toad-async-direct-open-3`, `toad-polymorphic-async-navigation-4`, and
`toad-prepared-async-shell-open-5` retain the iteration evidence.

The expanded53-case pilot set has been verified (latest full run52passed, then
the remaining comms case passed after replacing frame-pause timing assumptions
with bounded domain-completion waits). New coverage gates sidebar hydration while
typing/switching, closes a view during publication, tests typed target dispatch,
validates lookahead bounds/disabled behavior, and checks unselected shells do not
start source presentation. An initial startup deadlock was fixed by keeping
`new_session_screen` independent of content-ready: app mounting must return before
its presentation callbacks can run. Retired-row publication and loading-indicator
shutdown regressions were reproduced and fixed. The final focused activation,
opening and sidebar-geometry rerun passed4cases. This remains a draft checkpoint.

### Structural follow-up preceding async activation

- Textual3412passed/1skipped/4xfailed excluding snapshots;25focused visual
  snapshots passed. Toad52pilots passed. Framework sources also received a final
  delayed-transition regression fix and Python3.9-compatible paint record cleanup,
  covered by the final framework run and the full native navigation workload.
- Native Footer reconciliation preserves binding/keymap authority and native key
  owners, including disabled/grouped states, owner changes and retirement during
  awaited publication. It has not independently established an end-to-end win.
- Shared paint validation now observes style/topology mutation epochs, avoiding
  repeated ancestor traversal when no input changed. Child-derived scrolling
  extents no longer refeed unchanged layout output into ancestor measurement.
- All-seven-filter/four-thread receipts (each72actions/52typed markers):

  | Candidate | Input median / p95 / maximum (ms) | Loop maximum (ms) | GC maximum (ms) |
  | --- | --- | --- | --- |
  | Footer reconciliation |54.09 /142.69 /227.30|151.73|88.22|
  | Paint mutation epoch |47.27 /102.22 /149.74|116.24|84.63|
  | Scrolling extent output |55.21 /97.47 /134.90|148.48|84.06|

  These are serial source-identified samples, not an isolated statistical proof
  for every change. All preserve masks and unsent drafts; all miss the target.
- Full native ten-tab navigation plus sidebar resizing completed83actions.
  Target-mode terminal flush: opening median696.19/max957.23ms (9opens),
  switching median169.34/max204.15ms (21non-no-op switches). Overall loopmax189.70,
  GCmax139.83ms; resize-loopmax101.57ms. Opening ready-handler completion is a
  separate measure: median831.72/max1093.16ms.
- Navigation attribution now identifies repeated cold sidebar preparation:
  warm switches spend about63–91ms in prepare_navigation and45–68ms in
  layout_navigation. Inactive native roster retirement reduces retained widgets
  but shifts remount/measurement work onto activation. This needs a bounded
  presentation-ownership solution rather than unbounded per-tab warm caches.
- Captured-session replay retains about3511–3560registered widgets, with701
  document-body owners and693–696dormant. Zero closed reactive subscriptions,
  zero closed arrangement/geometry entries in the inspected owners. Most of the
  remaining footprint is outer message/chrome widgets, which remains unfinished.
- Two loaded replay spinner intervals each produced180updates in3seconds at
  requested60Hz, max3.19/2.45ms frame work, zero layout/CSS calls. This is headless
  steady-state frame work, not terminal FPS or concurrent-input acceptance.
- Private capture prefixes: `toad-footer-reconciliation-filters-1`,
  `toad-current-reconciliation-profile-1`, `toad-paint-mutation-epoch-filters-1`,
  `toad-paint-epoch-layout-causes-1`, `toad-scroll-measurement-output-filters-1`,
  `toad-live-replay-footer-paint-epoch-1`, `toad-current-structural-navigation-1`.
  Raw data remains outside Git. GC policy is unchanged. Main integration remains
  deferred by user instruction.

### Accumulation status

The reproduced retention bugs are fixed: quiet reactive publishers release closed
subscribers, removed children leave arrangement/StreamLayout caches, and compositor
maps/layer projections release retired widgets. The captured-session replay
reported zero closed reactive subscriptions and zero closed arrangement/geometry
entries in inspected owners. Cold document bodies and inactive native rosters
also release their descendant presentation trees.

This does not establish a fully bounded or leak-free long-running application.
The shared projected-paging follow-up bounds normal filtered-window retention;
compatible committed off-tail live blocks now retire through the retained source.
Initial off-tail bootstrap, other local/chrome widgets and protected selection spans remain unfinished;
the diagnostic replay still observed some other closed widgets. Keep source-size
scaling and long-aging validation open rather than treating the fixed reproductions
as proof that all accumulation is solved.

### Earlier published receipts

- Full Textual suite at the latest framework checkpoint:3132passed,1skipped,
  4xfailed, excluding snapshot tests. The packaged Toad pilot runner passes49cases.
  Toad broad and focused receipts are detailed
  in the audit; regression failures were reproduced before the relevant fixes.
- All-seven-filter four-thread stress reproduced a real mount-supersession crash.
  After the fix it completed72actions and applied52/52typed markers to the correct
  drafts. Remaining input/stall outliers around200ms are **not** accepted as done.
- The portable-toolbox repeat also completed72actions/52typed markers with all
  masks restored; input acknowledgment still reached217ms. It is recorded as a
  passing workflow with failing performance, not a responsiveness success.
- Live sampling and DTO capture succeeded. The saved live workload was replayed
  headlessly in an isolated store across13views. It exposed costs absent from the
  small synthetic fixture, including hundreds of direct live blocks in one view.
- **Observer correction:** early navigation wrappers lost Textual decorator
  identity and dispatched transcript/ready handlers twice. A failing-before
  observer check now enforces one dispatch. Affected captures and the quoted
  740–850ms opening range are not valid acceptance baselines.
- Corrected first-frame policy comparison showed median target-mode flush about
  780ms (ungated control) versus691ms (gated), with content-ready medians about
  814/827ms. This is partial progress, not the target or proof of faster loading.
- Local display invalidation has semantic coverage, but one real-data replay
  had a 34 s wall/1.3 s CPU setter outlier. A later host check showed full swap,
  but the cause of that discrepancy remains unresolved. Keep that result visible
  and repeat with resource attribution before claiming a gain.
- The captured replay is loaded data/view state, not a full process checkpoint;
  the first bundle incompletely captures transient tool/live input metadata.
- The branch was developed from an older main revision. Integrating newer main
  changes is required before merge. The draft pins the tested core revision and
  Textual companion commit so the declared API dependency is explicit.
- A minimal306x80 headless spinner probe requested60Hz and recorded180updates in
  3seconds: frame-work p951.14ms/max2.23ms, zero layout/CSS-apply calls. That is
  component/compositor evidence, not a delivered-terminal-FPS or loaded-app claim.
- Follow-up captured replay (~6,500 mounted widgets, 13 views): large Thinking
  setter/restore used 15.0/13.3 ms versus 39.7/53.3 ms in a fresh published-source
  control. This isolates synchronous setter work; GC still reached 205.6 ms.
- Two loaded-scene spinner intervals each produced 180 headless compositor
  updates in three seconds at requested 60 Hz: maximum frame work 3.4 ms, no
  layout or CSS applications. This establishes this steady-state component's
  loaded-scene cost, not input performance during filtering or terminal FPS.
- Latest four-thread terminal worker-batch receipt completed all 72 actions and
  52 typed markers, but input acknowledgment max was 247.3 ms and loop max was
  200.0 ms (GC 126.3 ms). Bounded admission is not an end-to-end performance win.

## Next work

1. Quantify reactive-retention cleanup under aged/captured interaction churn.
2. Attribute the remaining filter pause to setter, allocation/GC, layout, paint,
   GIL and host scheduling separately; bound work rather than move the stall.
3. Complete source-size-independent presentation, especially off-tail bootstrap
   without canonical history and other local message/chrome owners. Filtered
   prefixes reuse bounded paging and compatible committed live blocks retire
   off-tail; extend coverage to protected-range scaling and long-aging cycles.
4. Establish simultaneous spinner/input budgets during filtering and loading;
   steady-state headless loaded-scene animation now has a measured receipt.
5. Repeat unprofiled real-terminal acceptance after correctness and source/receipt
   checks, then integrate the companion framework and current main.
