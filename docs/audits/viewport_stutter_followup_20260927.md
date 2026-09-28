# Viewport stutter follow-up

Base: merged Toad PR65 at `94507dd0e727acd9ba64494dfd477a33b4800da3`, with
merged Textual PR5 at `4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e` and the preserved
current-main core pin `b1e5bfd5c39ea69c507833e8ed5efc96a7fb038b`.

Status: **validated landing checkpoint; native latency remains follow-up work**.

## Current-main landing integration

The user approved merging Textual PR6, then Toad PR73 after checks, while another
agent retains ownership of installed comms-pin/runtime updates.

The performance branch now includes current Toad main through `a27814f`, preserving
its nominal core transcript/goal/queue/read-proof APIs, notification feedback and
visibility-scoped route observation. The final core pin is `ab98c1993013d659fb7cdf8d4c941225cb7cf5f9`;
Textual PR6 is merged at `6ac3cdd919b1bfb3333091c9ac94df6c114d9fa9`, whose Git tree
exactly equals tested candidate `bfdb4ad4`. The Channels retention fix `c2efb16` is included.
No production source was rolled back to the older performance baseline.

The first expanded integration run against main `d1794c9` / core `c895ff0` passed
88 of 95 pilots. Failures exposed fixture calls to removed core entry points,
premature reads before asynchronous panel visibility, and the old expectation
that inactive Channels rows disappear. Fixtures now call the canonical transcript
route/history/turn-lease owners, wait for native readiness, and assert retained
row identity rather than retirement. Message routing, read-ack and UI assertions
remain. The legacy replay tool's owner imports/calls were migrated too; old pickles
remain bound to their original DTO/runtime schema and are not a new replay receipt.

The comms scenario then exceeded its unchanged 100 s limit. The diagnostic showed
progress, but inactive retained rosters continued scheduling source polls. A new
regression failed before an active-screen guard at the existing polling boundary.
The guard is inside the normal shutdown error boundary; a preliminary placement
outside it exposed an empty-screen-stack shutdown race and was corrected. The
comms scenario then passed in 68.14 s, and the full repeat passed **125 tests and
73 subtests in 630.00 s** (95 pilots plus 30 queue/cursor unit cases), including
comms in 69.99 s. Peak memory was 550.4 MiB, zero swap. No deadlines were increased.

While that run completed, main added notification/activity and route-observation
changes (`75fcd89`, `16b0697`). They are now integrated with their four focused
pilots added to the full runner. The final runner includes 99 pilots and 30
queue/cursor unit cases. Runs remain serial,
one pytest worker, 4 GiB RAM cap and no swap; the new core lives in an isolated
validation environment rather than the shared installed runtime.

Fresh framework verification on `bfdb4ad4` passes **3,507 tests**, 1 skipped and
4 xfailed in 201.80 s, with a 250 MiB peak. The earlier broad-opt-in snapshot
result remains 92/93 matches; its zero-width-SVG mismatch reproduces on unchanged
baseline code and was not suppressed or updated. It also reproduces on the actual
PR base `4fa6a9c4`; normalized SVG comparison confirms identical baseline/candidate output.

Native current-stack captures:

- `toad-pr73-landing-native-filter`: 72 actions, 52 typed markers, all category
  masks and drafts retained. Input median/p95/max **34.04/51.97/60.64 ms**;
  layout median/p95/max **10.20/31.59/94.95 ms**; loop max **110.31 ms**;
  GC max **66.55 ms**. Peak scope memory 486.3 MiB, zero swap. This is one
  integration receipt, not a replacement for earlier repeated adverse tails.
- `toad-pr73-landing-native-navigation`: 83 actions, ten tabs and eight native
  sidebar resize drags complete. Forty repeatedly observed channel keys across
  ten modes retain their object IDs. Peak 522.6 MiB, zero swap.
- The first identity analysis of the filter capture incorrectly grouped left
  Channels rows together with right-side relationship rows for the same target.
  Inspection showed one stable ID per owner/class, not recreated Channels rows.
  The observer now records native Channels ownership and the analyzer filters on
  that authority; the subsequent navigation receipt passes. No production row
  behavior or acceptance assertion was changed to accommodate that tool error.

The newer combination's first full run passed 126 cases and 73 subtests, with
three fixture failures: an incompletely initialized synthetic Agent caused an
unavailable-status layout change during a controlled checkpoint; the comms test
observed its final reply before independently prepared thinking content; and a
notification fixture deleted its wire before executor reads finished. The Agent
fixture now initializes the native superclass, the transcript wait covers both
required bodies, and executor reads drain before cleanup. Their semantics are
unchanged. Five affected/related pilots pass after those corrections.

The late comms click additionally required completed roster reconciliation and
an exposed native hit target, not simply membership in the visible geometry map.
The existing 10 s navigation and 100 s whole-pilot limits remain; the corrected
comms case passes in 57.14 s. The final full repeat passes **129 tests and 73
subtests in 637.09 s** (all 99 pilots plus 30 queue/cursor unit cases), including
comms in 65.33 s. Peak memory 540.8 MiB, zero swap. All owned native scopes were
stopped after capture. Textual was merged only after its checks, with exact-tree
readback against the tested candidate.

During that full run, main advanced through pin-only PR104/105 (`a27814f`), adopting
the merged Textual SHA and core `ab98c19`. The full run above used its explicitly
selected isolated `0c63715` environment; it is not relabeled as an `ab98c19` run.
The newer core pin is preserved and received a separate targeted run of native
input, owner/route, transcript, queue, maintenance and observed-status contracts:
**all 24 passed in 235.33 s**, with comms in 63.53 s, peak 532.1 MiB and zero swap.
No Toad production source changed in the pin-only merge. Scoped lint and diff
checks pass. There are no configured GitHub checks on either PR; the explicit
local receipts above are the validation evidence. The user authorized this
checkpoint to land before further optimization, without changing the shared
installed runtime here.

## Widget cohorts and Channels correction handoff

The next read-only census (`toad-widget-cohorts-1`) completed the 72-action/52-marker
fixture and counted 341,860 tracked objects. Live widget/message-pump cohorts were:

| Screen cohort | Transcript fragments | Sidebar | Chrome/other |
| --- | --- | --- | --- |
| Active |128|146|100|
| Inactive |336|285|327|

Inactive means owned by a screen outside the active/backdrop set; it can include
prepared screens. Shallow dictionary byte counts are explicitly not transitive
heap ownership. No collection was forced. This identifies larger source-backed
subtrees for future investigation rather than proving an aging bound.

The user then reported Channels reloading on every tab switch in the actual
agent-comms pin. Its Toad base `8adfcad` uses core `f7716d5` and Textual `4fa6a9c4`,
a newer core API than this performance branch. A pin-compatible fix is pushed as
**`c2efb1623cea9833601cf659bac2bef62d7b9e46`** on
`fix/preserve-channel-rosters-20260928`: it preserves channel row trees across
switches, retains route validation, and performs normal teardown on close.
The new regression fails before and passes after; 17 targeted pilots, ten-tab
headless returns and a 43-action native capture pass. Observed native channel
identities remain unchanged across 44 repeated keys in 11 modes.

The user assigned comms-pin updates to another agent. Preserve this correction
when reconciling current main into the performance branch: reducing retained
widgets must not reintroduce unnecessary channel reloads. The cohort census above
predates that correction and is not a post-fix memory measurement.

## Higher-level arrangement reuse

The next increment targets duplicated recursive work, rather than another leaf
allocation. A four-toggle diagnostic recorded identical transcript-grid placements
at available heights 70 and 144 (and corresponding width-dependent content
heights). The grid arranged again for measurement and final placement. It had
18 misses in 19 calls; the local candidate reduced that to 9 misses in 20 calls.
The inclusive grid span sum went from 75.79 to 41.09 ms. Instrumentation and
recursive timing are diagnostic evidence, not an additive end-to-end saving.

The framework extends its declaration-owned dependency strategies to whole native
arrangements. `CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT` is disabled by default and
retains the existing bounded cache. Grid and stream policies check their direct
content-measurement paths, not merely child box heights. Unknown/custom methods,
height-sensitive tracks/extrema, docking/splits/overlays and non-default alignment
retain native context. Width, viewport and optimal/greedy state stay distinct.

The first candidate exposed over-invalidation: a style or attachment change in a
sibling sidebar invalidated transcript proofs through global epochs. `Styles`
now projects its mutation epoch to its owning node and ancestors, including raw
writes without refresh. Measurement reuse consumes that subtree projection plus
the existing child/geometry revisions. Parent-sensitive extrema retain immediate
parent style and attachment stamps. There is no second layout model or cache of
widget references in these proofs. Mutation boundaries own invalidation, and
retirement clears the derived state.

Toad enables this contract on transcript fragments/pages/history, conversation
contents/grid, and its named sidebar container classes. The margin-trimming and
grid-stretch hooks declare their complete height-independent behavior. Native
selection, hit testing, scrolling, focus and source identities remain authoritative.

### Verification

- Eight initial reuse/invalidation tests failed on the old implementation; the
  sibling-locality test then failed with global-epoch invalidation. The final
  framework suite passes **3,505 tests**, 1 skipped, 4 xfailed, in 198.80 s with a
  250.4 MiB peak. The new 32 cases exercise native placement parity, raw/pre-idle
  mutations, sibling locality, parent extrema and conservative fallback.
- Broad diagnostic opt-in across native widgets matched **92 of 93 snapshots**.
  `test_dock_align` also fails on unchanged `ec244df7` and with both flags off.
  Its sole SVG difference is an extra zero-width background rectangle; the
  candidate/default SVG equals the unchanged baseline after normalizing generated
  IDs. No snapshot was updated and no assertion weakened. Retain this pre-existing
  serialized-SVG mismatch explicitly rather than claiming all snapshots pass.
- Five focused Toad frame/lifetime/filter pilots passed. Full companion validation
  initially passed 79 cases; the late comms channel click failed with a zero-size
  row at 71.90 s. The test now waits for the native visible row before clicking,
  keeping readiness, click and destination within the existing 10 s navigation
  deadline. Its unchanged 100 s pilot limit remains; the isolated case passed in
  93.67 s. The final full run with the paint-retention policy below passes all 80
  pilots in 517.29 s (comms: 73.40 s), at 473.1 MiB peak and zero swap.

### Native results

Controls use detached Toad `84d25ae` / Textual `ec244df7`. Same CPython 3.14.2,
dependency files, observer and fixture; arrangement tracing disabled. All four
serial captures completed 72 actions/52 markers with filters and drafts intact.

| Capture | Input median / p95 / max ms | Layout median / p95 / max ms | Loop max ms | GC max ms |
| --- | --- | --- | --- | --- |
| `toad-arrangement-control-1` |29.35 /51.80 /59.10|12.24 /32.63 /108.93|116.92|61.81|
| `toad-arrangement-candidate-1` |35.10 /60.02 /64.00|11.17 /33.73 /91.74|132.07|79.21|
| `toad-arrangement-candidate-2` |28.20 /58.33 /67.15|11.02 /28.99 /82.84|89.98|66.77|
| `toad-arrangement-control-2` |37.80 /58.98 /69.75|12.92 /36.48 /129.41|144.20|71.97|

The two candidates reduce median layout time and the measured layout maximum, but
input and loop tails overlap the control range. Candidate1's worst gap includes
a 79.21 ms zero-collected GC pause; candidate2's worst sidebar gap includes
43.94 ms arrangement and 29.49 ms paint. These spans overlap their enclosing
layout measurement and must not be summed with it. This is a measured reduction
in duplicated layout work, not universal sub-50-ms latency. Native scope peaks
were below 473 MiB, zero swap; all owned capture scopes were stopped afterward.

### Retire paint graphs without making tab geometry cold

The existing all-presentation retirement policy was tried first in a disposable
fixture (`toad-arrangement-cold-1`). It reduced closing tracked objects to 334,745
and GC maximum to 53.39 ms, but a tab revisit took a 129.82 ms loop gap, including
62.87 ms arrangement. This aggressive setting is not enabled in Toad.

The candidate instead declares `SessionView.RETAIN_INACTIVE_PAINT = False`.
The framework defaults this new policy to true; opt-out releases render/line/style
caches while preserving measured boxes, arrangements, compositor geometry and
the source model. Visible backdrops are protected. Existing full-presentation
retirement and closing still release both paint and measurements. A regression
fails on the old framework and verifies cache release, retained arrangement
identity, stable source widgets and identical painted pixels on resume; a second
test protects a visible transparent-overlay backdrop.
The final combined framework run passes **3,507 tests**, 1 skipped, 4 xfailed,
in 200.19 s at a 250.3 MiB peak. All 80 companion pilots pass in 517.29 s with
unchanged assertions/scenarios and the original per-pilot/navigation deadlines.

Same 72-action/52-marker fixture, masks/drafts retained:

| Capture | Input median / p95 / max ms | Layout median / p95 / max ms | Loop max ms | GC max ms |
| --- | --- | --- | --- | --- |
| `toad-arrangement-cold-1` (full-cold, rejected default) |32.19 /50.87 /69.63|11.68 /32.11 /78.24|129.82|53.39|
| `toad-arrangement-cold-paint-1` (diagnostic paint-only opt-out) |33.46 /56.30 /63.23|10.86 /30.33 /92.65|99.16|45.01|
| `toad-arrangement-cold-paint-final-2` (declared policy) |33.27 /54.51 /118.96|10.91 /32.18 /94.02|106.62|62.56|
| `toad-arrangement-cold-paint-final-3` (declared policy) |31.13 /49.08 /67.38|10.86 /31.33 /77.68|115.37|54.92|

The paint-only closing censuses contain 343,458 / 345,040 / 344,337 tracked objects
and 3,286 / 3,265 / 3,290 strips, versus roughly 12,000 strips when retaining all
inactive paint (controls: 381,947/383,672 tracked objects and 11,998/12,463 strips).
Source widgets remain mounted. The final scopes peak below 467 MiB
with zero swap. One final input tail still reaches **118.96 ms**; do not discard
it or claim a universal maximum-input improvement. The retained paint graph and
typical layout work are reduced,
but the sub-50-ms objective remains unmet. Probe flags are recorded separately
from the selected screen's declared retention policy in its live snapshot.

## Version-specific GC and paint-owner retention

The acceptance environment uses GIL-enabled CPython3.14.2, not the currently
documented3.14patch. Online research was checked against versioned sources:

- [3.14.2 collector source](https://github.com/python/cpython/blob/v3.14.2/Python/gc.c#L1455-L1659):
  `mark_at_start` walks the objects reachable from global roots and thread stacks,
  with the explicit comment "TO DO -- Make this incremental". Later increments
  also expand through unvisited reachable objects. The nominal scan fraction is
  not a hard object-count or pause-time bound. A collection that frees no objects
  can still traverse a large live graph. A `strip.crop` trigger stack does not
  identify the owner of that entire graph. Callbacks also include marking-only
  increments and early returns while scan-work debt is negative; their count and
  tiny median are not equivalent to full young-generation scans after the revert.
- [3.14.2 GC design](https://github.com/python/cpython/blob/v3.14.2/InternalDocs/garbage_collector.md):
  reference counting handles ordinary acyclic release; cyclic GC scans tracked
  containers. Reducing live graph size and breaking accidental owner retention
  help independently of the location that triggers collection.
- [3.14.5 GC API](https://docs.python.org/release/3.14.5/library/gc.html) and
  [the core-team revert discussion](https://discuss.python.org/t/reverting-the-incremental-gc-in-python-3-14-and-3-15/107014):
  3.14.5restored the three-generation collector. Generation1again means the middle
  generation, and threshold2is active. The previous3.14incremental collector and
  the free-threaded collector have different mechanics; neither label is a latency
  guarantee. Both interpreters tested here report the GIL enabled.

### Isolated runtime-package comparison

Unchanged Toad96e088f/Textual39b15d12; identical dependency directories and the same
720-event fixture. The installed system3.14.6interpreter was used through a fresh
isolated venv, reusing the exact cp314dependency files. Its GCC16.1.1build differs
from the standalone3.14.2Clang21.1.4tail-call/BOLT build, so this is a comparison
of runtime packages, not an experiment isolating only the GC implementation.
No shared environment was replaced. Each serial4GiB/no-swap capture completed
72actions/52markers and preserved every filter mask and draft.

| Capture | Input median / p95 / maximum ms | Loop max ms | GC max ms |
| --- | --- | --- | --- |
| `toad-gc-system-3146-1` |34.45 /62.97 /216.10|204.90|163.91|
| `toad-gc-standalone-3142-1` |32.11 /50.31 /69.93|110.25|69.17|
| `toad-gc-system-3146-2` |34.21 /69.80 /87.82|126.76|124.69|
| `toad-gc-standalone-3142-2` |36.20 /53.89 /104.85|105.36|70.56|

System3.14.6had a163.91ms generation2pause inside the216.10ms input delay;
another138.79ms generation2pause collected zero objects. Its second run still
had a124.69ms pause. The repeat3.14.2input outlier overlapped41.06ms GC collecting
16,670objects. Keep all tails: upgrading the runtime is not an established
responsiveness fix for this fixture. Scope peaks were below477MiB, zero swap.
Thresholds remained native:3.14.2`(2000,10,0)`,3.14.6`(2000,10,10)`.

The runner now records the selected interpreter's exact version, executable,
GIL/build configuration and **separate probe** thresholds in its manifest. Live
UI thresholds/stats remain in the state snapshot. Census measurement entries now
compare against the owner's published generation (including structure/proof
epochs), rather than misclassifying current entries with the obsolete two-field
suffix. These labels describe stored generations, not whether a new measurement
would retire them. The census also records color-cache occupancy/hits/misses.

### Paint color memo ownership correction

`StylesCache.get_inner_outer` was an instance method decorated by a process-wide
1024-entryLRU. Its computation used only two colors, but its key also retained
each per-widget paint owner. That kept retired caches and their lines reachable
until eviction, and recomputed identical color pairs for different owners.

The companion change declares this pure operation static. The same bounded cache
now owns only color inputs and immutable style results. `StylesCache.clear` also
releases its reusable padding strip; previously a direct clear/re-render could
retain the old background. Three deterministic regressions failed before the fix:
owner release without forced GC/eviction, cross-owner reuse, and changed padding
paint after clear. The focused52-test paint/lifetime/strip suite passes afterward.
Full framework verification passed3,473tests (1skip,4xfail) in196.56s, with a
245.8MiB peak. All60border/padding/opacity/tint/theme/scrollbar/Markdown snapshots
passed in14.31s. The first full Toad run passed79pilots; comms exceeded its unchanged
100s deadline (536.46s total,485.8MiB peak). A read-only diagnostic then completed
all comms interactions in71.03s. The second full run passed **all80pilots in525.03s**,
including comms in88.08s under the same100s deadline, at542.1MiB peak and zero swap.
The initial timeout remains evidence rather than being attributed to the paint fix
without proof; no assertion, scenario or deadline was weakened.

Same3.14.2runtime/dependencies, same observer, framework control39b15d12and the
paint-owner correction; each72actions/52markers with all masks/drafts preserved:

| Capture | Input median / p95 / maximum ms | Loop max ms | GC max ms |
| --- | --- | --- | --- |
| `toad-paint-owner-control-1` |32.60 /57.29 /111.20|96.62|66.79|
| `toad-paint-owner-candidate-1` |29.63 /59.76 /66.56|153.84|67.04|
| `toad-paint-owner-candidate-2` |29.60 /54.93 /70.91|158.03|68.12|

The closing census shows color-memo entries1,024in control versus6/7in candidates;
misses2,665versus6/7. Tracked `StylesCache` counts were1,890versus1,429/1,461,
and `textual.style.Style` counts3,335versus1,281/1,288. Total tracked objects were
390,357versus380,879/384,082. Census endpoints depend on collection timing; the
deterministic weak-reference regression proves the ownership correction itself.
Native scope peaks were below475MiB, zero swap, with owned children retired.

Both candidate worst loop gaps overlap a54.84/57.26ms zero-collected GC pause
during sidebar paint, on top of45.24/56.38ms arrangement. These overlapping spans
are not additive. GC maxima did not improve and loop maxima worsened, despite
lower input maxima. Preserve those failures: this is a verified lifetime/cache
correction, not a robust worst-stutter or universal sub50ms win. GC on another
Python thread can also block the GIL-enabled UI; the control's66.79ms collection
was not on the UI thread. `analyze_trace.py --gc` separates callback generations
and threads and reports first/last censuses. Generation labels must be interpreted
with the recorded runtime version.

## Structural measurement correction

Dependency: [Textual PR6](https://github.com/OpenHCSDev/textual/pull/6), pinned at
`6ac3cdd919b1bfb3333091c9ac94df6c114d9fa9` (structural fix, owner-clock idle
measurement, declared box/arrangement reuse, local invalidation and paint lifetime). The merged framework baseline alone
does not contain this correction.

The clipped frame was reproduced with committed geometry evidence: the history
container retained a29-row box while its page already occupied33rows. `NodeList`
publishes structural/display revisions before idle layout messages propagate.
Textual's arrangement cache observed that revision, but its intrinsic box-size
cache did not. The removed full-map lookup had masked that inconsistent state.

The companion Textual change includes the existing child-structure revision in
the box-model cache generation. No extra ancestor traversal, new parallel state
or unconditional layout pass is introduced. Two deterministic tests failed before
the change: nested admission and display-constraint mutation before idle delivery.
They pass after it, retaining width reuse and obsolete-generation retirement.
The full companion framework run passed3,442tests (1skip,4xfail) in193.07s,
followed by six passing scrollbar/Markdown/prune snapshots. A prior run omitted
syntax extras and failed three language tests; the corrected run above includes
them and passes. This dependency-path mistake is separate from the geometry fix.

The progressive-tail diagnostic passed six consecutive runs. The initial80-pilot
Toad run then passed79cases, including `committed_history`; only the large comms
scenario exceeded its unchanged100s deadline. The process-idle measurement issue
described below was corrected without changing that deadline. The subsequent
full run passed all80pilots in524.28s; the framework passed3,446tests (1skip,4xfail)
in195.47s. After withdrawing the arithmetic experiment, the final isolated comms
rerun passed in61.04s. Validation used one worker and no overlapping benchmarks.

## Latest controlled measurements and memory

### Follow-up attribution

A diagnostic of the large comms pilot measured70.45s in272process-CPU idle waits
and9.99s in380message barriers over96.43s. Sixty idle waits exceeded half a second.
The UI owner was being charged for independent worker CPU. Using the calling
thread's CPU clock completed the same interaction assertions in75.27s with the
deadline unchanged. Four framework regressions ensure background work does not
extend an idle UI wait, while active UI work and minimum waits retain their limits.
This corrects test synchronization; it is not a native-latency performance claim.

An integer-before-Fraction arithmetic simplification was tested and withdrawn
because the native comparison did not establish an improvement. Preserve the
failed timing evidence, each72actions/52markers with masks/drafts retained:

| Capture | Input median / p95 / maximum ms | Loop max ms | GC max ms |
| --- | --- | --- | --- |
| `toad-integer-box-control-1` |34.32 /54.29 /62.26|114.53|51.84|
| `toad-integer-box-candidate-1` (withdrawn) |33.07 /53.35 /113.27|120.47|61.25|
| `toad-integer-box-candidate-2` (withdrawn) |33.68 /79.31 /89.49|118.79|64.55|

The113.27ms outlier overlapped61.25ms UI-thread GC. That does not establish
causality for the arithmetic change, nor justify claiming a gain from its median.
The existing runtime rational computation remains; no new native speedup is claimed
for the idle-clock/test-tooling follow-up.

The optional box-model diagnostic (`toad-box-variants-sidebar-1`) recorded1,386
calls across four sidebar actions. It found repeated same-revision, same-result
page measurements at equal widths but different available heights (for example,
75x0 and75x144 both yielding75x143). These are candidates for dependency-aware
reuse; arbitrary/custom layout dependence on available height must still be
preserved. No speculative height-normalization cache is implemented here.

After the user's X11 restart, validation and native runs were serialized in user
cgroups limited to4GiB RAM with swap disabled. Full Toad validation peaked494.2MiB;
the native control/candidate peaked480.5/475.3MiB, with zero swap use. Only owned
test scopes/processes were retired; no user runtime was restarted.
The later all-green full runs peaked552.9MiB for Toad and249.3MiB for Textual,
again with zero swap. The arithmetic experiment's native scopes peaked below475MiB.

Serial72-action/52-marker runs, all filters/drafts preserved:

| Capture | Input median / p95 / maximum ms | Loop max ms | GC max ms |
| --- | --- | --- | --- |
| `toad-structural-box-control-1` |33.03 /73.49 /96.75|125.91|89.53|
| `toad-structural-box-candidate-1` |35.65 /56.90 /59.59|112.89|77.00|
| `toad-structural-box-candidate-2` |37.96 /61.93 /69.87|124.73|80.86|

Recorded anchor-triggered full geometry passes (at least3ms):22in control,0in
both corrected candidates. The repeated input tails improved in these runs, but
overall loop maxima still exceed100ms. Keep both repeats; there is no universal
sub50ms or indefinite-aging memory claim.

## Candidate

### Declaration-proved measurement reuse

The new companion framework surface `CACHE_HEIGHT_INDEPENDENT_BOX` is disabled
by default. This draft opts in the transcript fragment/page/history classes.
Method and layout owners declare dependency behavior once; a conservative proof
checks live CSS and child declarations before normalizing unused available-height
inputs. Unknown overrides and context-sensitive sizing retain native full keys.
The framework's existing cache budget and source-owned mutation epochs still own
retirement; proofs retain only data, not child widgets.

The native Markdown measurement and margin-trimming hooks declare their contracts.
The initial four-toggle diagnostic dropped page misses18to9 and fragment misses
312to129 (total box calls1,386to1,021). Local style-plan caching and shared child
proofs then removed duplicate dependency traversals; no performance is inferred
by summing these recursive call timings.

Initial serial native72-action/52-marker comparison, with all masks/drafts intact:

| Capture | Input median / p95 / maximum ms | Layout median / p95 ms | Loop max ms |
| --- | --- | --- | --- |
| `toad-height-reuse-control-1` |36.79 /68.20 /92.78|15.04 /46.25|129.65|
| `toad-height-reuse-candidate-1` |27.89 /56.90 /86.46|12.14 /33.98|159.08|

The candidate's worse loop maximum overlapped65.93ms GC. Keep that failure visible;
there is no universal maximum-stutter win. These preliminary timings preceded the
final conservative custom-scalar and raw-percentage fallback checks. Repeated
final-source measurements follow below.

Final correctness:3,470framework tests passed (1skip,4xfail),45snapshots passed
with broad native opt-in, and all80Toad pilots passed in526.41s. A preliminary
79-pass run timed out on a late channel revisit; the test now explicitly checks
that its native row click succeeded, and the full final run passes with the same
deadline. The frame stability and content assertions remain unchanged.

Final-source serial native runs, each72actions/52markers with masks/drafts intact:

| Capture | Input median / p95 / maximum ms | Layout median / p95 ms | Loop max ms | GC max ms |
| --- | --- | --- | --- | --- |
| `toad-height-reuse-control-2` |30.68 /55.41 /72.71|14.55 /43.58|162.31|76.08|
| `toad-height-reuse-final-1` |28.60 /55.60 /80.32|12.52 /33.45|152.70|63.90|
| `toad-height-reuse-final-2` |37.45 /66.03 /146.59|13.55 /36.96|141.53|87.10|

Layout p95 improves in both repeats, but the maximum-input target does not.
The146.59ms input outlier overlapped87.10ms UI-threadGC. Do not replace that
failure with the better median or one favorable maximum. Final framework/Toad
validation peaked247.3/476.7MiB; native control/candidate peaks were below475MiB,
all with swap disabled. Remaining work includes GC/paint tails and newer-main
reconciliation before landing these drafts.

### Tail anchoring

`HistoryAnchor` selects an immutable `TailAnchor` or `RecordAnchor` from current
reader intent. Stored policies own compensation; the screen directly calls their
`before_layout`, `restore` and geometry-target contracts. Tail capture no longer
reads a record offset that bottom anchoring never consumes. Record anchoring keeps
its previous offset compensation. Intent transitions rebind before layout so a
reader who scrolls during admission is not pulled back to the tail.

The final draft conservatively keeps the original target-path publication for
both policies. Only the record policy measures the target's offset. The first
measured candidate also omitted tail target paths; that additional change was
withdrawn while investigating progressive-tail rendering.

New `tail_anchor_policy_pilot` fails on the landed baseline when tail capture
requests unnecessary offset geometry. It verifies tail-to-reader and reader-to-tail
transitions during mutations and stable painted record positions. The runner also
includes the existing 2,000-record `history_anchor_geometry` regression.

## Earlier evidence and reproduced failure

- Focused anchor/checkpoint/lifetime suite:6passed18.29s on the initial candidate.
- Initial broader run:77passed,2failed. The route-admission fixture failed while
  deleting its disposable wire with executor work still running; the draft adds
  an executor drain after UI shutdown, preserving its existing route assertions.
- After restoring conservative tail target publication and draining that fixture:
  **78passed,1failed** in269.84s, excluding the separately exercised comms pilot.
- The earlier failure was `committed_history`: during progressive older-page
  admission one painted frame temporarily omits the canonical final reply, despite
  reporting a bottom scroll position. The assertion is unchanged and must remain.
- Three isolated repeats each of candidate and baseline pass this checkpoint;
  the corresponding baseline broader run passes77cases in282.60s. This is not
  enough to label the candidate failure harmless. It was retained as a blocker
  until the structural-measurement defect above was reproduced and corrected.

Serial native72-action/52-marker fixture, all filters and drafts retained:

| Capture | Input median / p95 / maximum ms | Loop max ms | GC max ms |
| --- | --- | --- | --- |
| `toad-tail-anchor-control-1` |37.59 /78.85 /86.80|112.85|82.60|
| `toad-tail-anchor-candidate-1` (initial variant) |28.49 /57.06 /64.00|140.65|71.83|

Recorded anchor-triggered full geometry passes (observer records passes of at
least3ms):21in control,0in the initial candidate. Control maximum21.35ms. The
candidate's worst loop gap overlaps71.83ms UI-thread GC. Lower measured input
latency is not proof of an overall maximum-stutter reduction, and these numbers
predate restoration of conservative tail target publication. No final-candidate
latency acceptance is claimed.

Next: reconcile the draft with current main and reduce the measured duplicated
intrinsic subtree work plus remaining sidebar paint/GC tails. The painted-frame
assertion and per-pilot deadlines remain unchanged.
