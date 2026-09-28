# Viewport stutter follow-up

Base: merged Toad PR65 at `94507dd0e727acd9ba64494dfd477a33b4800da3`, with
merged Textual PR5 at `4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e` and the preserved
current-main core pin `b1e5bfd5c39ea69c507833e8ed5efc96a7fb038b`.

Status: **draft; tail-frame regression and comms test-timeout resolved;
remaining native latency targets and current-main reconciliation are open**.

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
`ec244df727c586bd45edaf34a1f9a0c09d145918` (structural fix, owner-clock idle
measurement, opt-in declaration-proved box reuse and paint memo ownership). The merged framework baseline alone
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
