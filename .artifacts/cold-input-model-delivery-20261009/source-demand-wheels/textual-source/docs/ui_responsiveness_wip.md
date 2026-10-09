# UI responsiveness framework checkpoint

Draft companion to the OpenHCSDev Toad responsiveness investigation.

- Primary lifetime issue: https://github.com/OpenHCSDev/textual/issues/4
- Filtering: https://github.com/OpenHCSDev/toad/issues/59
- Bounded history/worker views: https://github.com/OpenHCSDev/toad/issues/61
- Animation budget: https://github.com/OpenHCSDev/toad/issues/64

## Whole-arrangement reuse and subtree-local invalidation

The companion also opts out of `Screen.RETAIN_INACTIVE_PAINT` (framework default
true). Widgets expose `_release_paint` separately from complete presentation
retirement, preserving measurements and scene geometry while retiring cached line
and style graphs. Native screen ownership protects visible backdrops. A failing-
before regression verifies release, retained arrangement identity and identical
resume pixels; another protects a transparent-overlay backdrop. All-cold retirement
was tested but left disabled because rebuilding geometry caused a 130 ms revisit.
Paint-only retirement reduces retained strips from roughly 12,000 to 3,300; final
GC maxima are 62.56/54.92 ms. One input still takes 118.96 ms, so this is not a
universal worst-input win. Final framework validation passes 3,507 tests (1 skip,
4 xfail) in 200.19 s at 250.3 MiB peak. All 80 companion Toad pilots pass in
517.29 s at 473.1 MiB peak and zero swap; comms takes 73.40 s under the unchanged
100 s limit. Its earlier zero-size-row click failure remains documented; readiness,
click and destination now share the original 10 s navigation deadline.

The next candidate lifts the declared height-dependency proof to complete
`DockArrangeResult` reuse, skipping recursive intrinsic measurement followed by
the same placement at a different available height. The new
`Widget.CACHE_HEIGHT_INDEPENDENT_ARRANGEMENT` remains opt-in and uses the existing
four-entry arrangement cache. Unknown hooks/layouts, dock/split/overlay behavior,
alignment, height-relative tracks/scalars and custom direct content measurement
retain the complete input context. Width, viewport and optimal/greedy mode remain
distinct. Grid/stream declarations follow their direct content-measurement paths;
a constant child box alone is not proof of constant content height.

`Styles` publishes its existing mutation epoch to its owning DOM subtree and
ancestors, including raw set/clear/reset/merge operations without refresh. Proofs
and normalized measurements consume that local projection with native child and
geometry revisions. Unrelated sibling style/structural edits no longer invalidate
the transcript. Parent-sensitive box extrema also retain the immediate parent's
native style key and a local projection of the parent's attachment revision.
No widget references are stored in proof keys, and presentation retirement clears
the derived proof and bounded result caches.

The first four-toggle diagnostic found 18 transcript-grid arrangement misses;
the local candidate had 9. Its inclusive grid span sum fell from roughly 76 to
41 ms, but recursive/instrumented spans are not end-to-end acceptance evidence.
New tests cover native placement parity, pre-idle/raw mutation, sibling locality,
parent extrema, context-sensitive grid tracks and unknown hooks/scalars. The full
framework passes 3,505 tests (1 skip, 4 xfail) in 198.80 s at 250.4 MiB peak.
Broad native opt-in matches 92/93 snapshots; the one docking mismatch also occurs
on unchanged ec244df7 with reuse disabled and differs only by a zero-width SVG
background rectangle. Candidate/default SVG equals that baseline. No snapshot
expectation was changed.

Four serial native runs preserve all 72 actions/52 markers. Controls have layout
median/max 12.24/108.93 and 12.92/129.41 ms; candidates 11.17/91.74 and 11.02/82.84 ms.
Input maxima 59.10/69.75 ms in controls versus 64.00/67.15 ms in candidates and
loop maxima 116.92/144.20 versus 132.07/89.98 ms remain overlapping. Keep the bad
tails: this removes duplicated work, not all maximum-stutter failures. Complete
measurements and companion validation are in the Toad audit.

## Paint color memo ownership

`StylesCache.get_inner_outer` computed only from its two color arguments, but its
global1024-entryLRU also keyed on the instance. That retained retired per-widget
paint caches and their lines until eviction, and duplicated identical color
results across owners. The operation is now static: the same bounded memo retains
only colors and immutable style results. `clear()` also releases the reusable
padding strip so a cleared scene cannot reuse its old background.

Three regressions fail before/pass after: immediate owner release without forcing
GC or evicting the memo, cross-owner color reuse, and changed padding paint after
clear. The focused paint/lifetime/strip suite passes52tests; the full framework
passes3,473tests (1skip,4xfail) in196.56s at245.8MiB peak. All60relevant visual
snapshots pass. Native closing color-cache entries drop1,024to6/7and tracked
paint-cache owners1,890to1,429/1,461. Input maxima111.20ms in control versus
66.56/70.91ms in candidates do not imply a universal win: loop maxima worsened
96.62ms to153.84/158.03ms with GC overlapping sidebar painting. GC maxima remain
about67–68ms. Full evidence and runtime comparison are in the companion Toad audit.

The online GC investigation is version-specific. CPython3.14.2's incremental
collector still has a non-incremental global-root/stack marking phase;3.14.5
restored three generations. Both tested runtime packages still had large pauses
(3.14.2up to70.56ms; system3.14.6up to163.91ms in the fresh comparison). Their
compiler/build flags also differ. Removing accidental owner retention is justified
by the lifetime regression; no universal latency win is inferred from that alone.

## Structural measurement revision follow-up

### Opt-in available-height-independent box reuse

`Widget.CACHE_HEIGHT_INDEPENDENT_BOX` is an opt-in reuse contract, disabled by
default. Native method/layout declarations resolve whether a box can change when
only available container height and its fractional unit change. Positive proofs
normalize those two cache-key members; width, viewport, width fraction, greedy and
constraint inputs remain distinct. Existing native style/tree/structure epochs
invalidate derived proofs and obsolete cache entries; no second source model or
unbounded result cache is introduced.

Vertical/horizontal flow and stream intrinsic measurement declare their behavior.
Unknown method/layout/hook/scalar overrides, height-relative units, fill height,
fractional height bounds, docking/splits/overlays, alignment, and the native
zero-height max-bound exception conservatively retain context. Flow proofs also
preserve native percentage-child stretch behavior even for raw width-axis height
scalars. A method declaration must describe the complete implementation, not just
its call to `super()`. Dynamic method replacement requires disabling the opt-in
or rebinding the declaration on a class.

Toad opts in its transcript fragment/page/history owners and declares the native
Markdown height and pure margin-trimming hooks. Native result-oracle tests cover
relative sizing, extrema, custom behavior, style/structural invalidation, width,
viewport, padding, margins, offsets and greedy-mode changes. A diagnostic enabling
reuse broadly across native widgets passed45scrollbar/Markdown/grid/prune snapshots.
Final validation passed3,470framework tests (1skip,4xfail), all80Toad pilots and
45broad-opt-in snapshots. Framework/application peaks were247.3/476.7MiB with
zero swap under the4GiB cap. One preliminary comms run missed a late navigation
receipt; the click is now explicitly asserted, and the full rerun passed without
changing deadlines.

Matched native controls/candidates retained72actions/52markers. Final layout p95
was43.58ms in control versus33.45/36.96ms in two candidate runs. Input maxima were
72.71ms versus80.32/146.59ms: the latter overlapped87.10ms UI-threadGC. This is a
measured layout-cost reduction, not a robust maximum-input or sub50ms result.

The subsequent pilot-idle correction measures CPU on the calling event-loop
thread instead of the whole process. Background preparation can remain busy after
UI messages drain; it must not force every pilot pause to its one-second limit.
The helper's minimum/maximum waits and active-UI behavior are unchanged. Four
deterministic clock tests preserve those boundaries; the diagnostic comms fixture
completed in75.27s versus70.45s spent in process-idle waits alone during an earlier
96.43s interrupted diagnostic. This is a test-harness correction, not an advertised
native UI speedup. Native input scheduling and GC policy are unchanged.

An exact integer-before-Fraction simplification was tested but withdrawn: native
maximum input delay was62.26ms in its control versus113.27/89.49ms in the two
candidate runs. No end-to-end benefit was established, so the existing rational
layout computation is retained. Those failed timing receipts remain in the audit.

The viewport-stutter follow-up exposed a stale intrinsic-size cache during
progressive child admission: a parent could retain a29-row box while its child
already arranged33rows, clipping the tail for one frame. Native `NodeList`
propagates structure/display revisions synchronously, but the box cache previously
waited for the later layout notification. Arrangement and box measurement could
therefore describe different child structures in the same frame.

The box-model revision now includes the existing native child-structure revision.
Obsolete entries are retired through the same cache-generation boundary. There
is no extra ancestor walk, duplicate revision registry or forced full-map layout.
Two deterministic failing-before regressions cover nested admission and native
display-projection changes before idle notification delivery; existing cache tests
retain width reuse and obsolete-generation retirement assertions.

The Toad progressive-tail diagnostic passed six consecutive runs with this fix.
The corrected-environment framework run passed3,442tests (1skip,4xfail) in193.07s,
and six focused scrollbar/Markdown/prune snapshots passed. The framework job peaked
246.5MiB under a4GiB/no-swap limit.
The initial80pilot run passed79cases including the prior frame failure; the large
comms case exceeded100s. After the owner-clock correction, all80pilots passed
in524.28s and the framework passed3,446tests (1skip,4xfail) in195.47s. After
withdrawing the arithmetic experiment, the final isolated comms rerun passed
in61.04s with the same100s deadline. Full Toad validation peaked552.9MiB and
framework validation249.3MiB, both with zero swap. Two earlier serial native
candidate runs preserved72actions/52markers and recorded input maxima59.59/69.87ms
versus96.75ms in the matched landed control. Anchor-induced full geometry passes
fell22to0, but loop maxima112.89/124.73ms still miss the overall stutter target.
Validation uses one worker with4GiB/no-swap limits.

## Removal completion and input ingress checkpoint

Native key-route evidence exposed an unrelated teardown barrier: a key entered
the app queue after5ms but waited another86ms before dispatch while widget removal
was being awaited through `App.call_next`. `AwaitRemove` now owns one shared
completion independently of the receiver's message pump. The app observes that
receipt only once it is done. Explicit waiters still wait for actual removal and
publication; cancelling a waiter cannot cancel node teardown or its final callback.
Self-removal retains its non-deadlocking semantics. Completed receipts release the
removed tasks, callback and task context instead of retaining the retired tree.

This also removes duplicate post-removal callbacks when both the caller and the
automatic receiver await the same receipt. Four failing-before regressions cover
input blocked by a held unmount, duplicate publication, cancellation propagation
and retired widgets retained by a completed receipt. Further tests cover async
publication cancellation, error replay and self-removal.

Driver ingress directly schedules the declared `App.post_message` operation on
its owning event loop. The previous coroutine adapter only called that method,
but added an unused cross-thread Future and an extra loop turn before enqueueing.
Tests verify one-handoff ordering and native bindings/focus/paste behavior.

Current full verification: **3,440 passed,1skipped,4xfailed** excluding snapshots;
**56 Toad pilots passed**. The focused native prune snapshot also passes.
Two serial unprofiled native runs completed all72actions/52typed markers:
input median24.56/29.42ms, p9554.36/49.04ms, maximum93.90/59.98ms. The earlier
published candidate's maximum was143.68ms. These are improved input-tail receipts,
not universal sub50ms acceptance: loop maxima remain121.48/103.23ms, including
roughly100ms sidebar layout+paint and62ms collections. Keep both repeated results.

## Declaration-bound dispatch checkpoint

`SelectorSet.check` owns target-only query matching. Single selectors and compound
selectors whose terms all apply to the target call the existing selector checks
directly. Relational selectors still use the existing interpreter and authoritative
CSS ancestry. This removes unnecessary ancestor-path allocation without caching
dynamic matches or adding widget-specific cases.

Reactive access now follows the same declaration-owned approach. At class
construction, `DOMNode` resolves each reactive to stored or computed access using
the concrete class's declarations. The descriptor directly calls that accessor on
reads, writes and recomputation. Stored reads do not rediscover compute methods or
recheck constructor readiness. Computed access preserves ordinary Python method
overrides; class metadata retains neither widgets nor bound instance callbacks.
Cold lazy initialization retains missing-constructor diagnostics and factory/
`Initialize` semantics. A private compute method introduced for an inherited
reactive is now correctly bound; a failing-before regression covers that bug.

Current checks: **3,431 passed, 1 skipped, 4 xfailed** excluding snapshots, and
**56 companion Toad pilots passed**. Thirteen selector tests cover old-interpreter
parity, custom ancestry, dynamic classes, inherited disabled state, focus and
elimination of unnecessary path construction. Six reactive access tests cover
probe-free reads, public/private inheritance, override dispatch, lazy defaults,
raw values, exception propagation and constructor diagnostics.

A focused sidebar action profile recorded **38,255 →1,972 total `hasattr` calls**;
reactive reads contributed **34,074 →0**. For roughly11.4k reads, cumulative
profiled reactive-get time fell from about36ms to8ms. This is a profiling result,
not an end-to-end timing claim. The latest unprofiled native filter workload
completed72actions and52typed markers, but input median42.63/p9595.47/
maximum143.68ms still misses the universal sub50ms target. Remaining layout,
paint, allocation/GC and consecutive-frame queue latency need further work.

## Included work

1. Reactive subscribers unregister watches from quiet publishers on close,
   cancellation and terminal message-pump cleanup. Reverse publisher ownership
   is weak. A real aged process had 2,268 closed FooterKey subscribers retained
   through Footer.compact; focused reproductions fail before this cleanup.
2. Optional DOM/message storage is lazy; immutable selector names are class
   metadata. Unused message signals are not allocated during dispatch, and a
   processed message is released before an idle queue wait.
3. Stopped/completed timers release callbacks/tasks. Closed widget/screen
   presentation state and compositor roots are cleared at their owning lifetime.
4. Box-model caches retire obsolete measurement revisions.
5. Viewport layout can retain declared anchor geometry paths without walking
   unrelated offscreen descendants. `_layout_geometry_targets()` is the screen
   declaration used by the application.
6. `_measured_virtual_size_requires_layout()` distinguishes committed layout
   output from an authored measurement input. Child-derived containers, including
   scrolling containers, no longer invalidate ancestor measurements merely for
   committing their extent. Watchers, authored changes and scrollbar visibility
   changes still invalidate normally. Custom extent-input widgets may override
   the hook.
7. `Stylesheet.is_local_display_class()` derives a conservative invalidation
   scope from parsed rules. Ordinary class mutation is unchanged; an application
   may opt into a node-local display update only when the declaration proves it
   safe. Descendant/custom/inherited rules force the normal subtree path.
8. `DOMNode.set_display_constraint(reason, allowed)` composes independent model
   visibility restrictions with the current authored CSS display value. Native
   displayed-child projections and layout are invalidated without restyling the
   subtree. Relative-child measurement observes the same effective display.
   `Stylesheet.references_class()` derives marker dependencies from parsed rules,
   including compound/ancestor selectors and source replacement/reparse.

## Structural follow-up

This draft includes the following structural changes. The companion Toad branch
pins this framework checkpoint. Correctness receipts do not establish latency targets.

- Removal retires parent arrangement and StreamLayout placements, inactive
  compositor maps, layer projections and pending widget invalidations. A native
  ownership reproduction failed against the previous source. Closed subscribers
  alone were not a sufficient lifetime check.
- Acyclic LRU storage releases acyclic payloads when the cache owner is dropped.
- Sparse horizontal exposure avoids painting covered parent backgrounds.
- Focus invalidation follows declaration targets; inherited paint is invalidated
  through style owners. Unchanged non-transition rules avoid animated rule-graph
  construction. Declared transitions still reconcile pending targets even when
  their current values are equal, including delayed transitions.
- Native layout and full-repaint intent commit in one frame. Content height
  measurement counts wrapping boundaries without constructing formatted lines.
- Screen resolution observes weak topology ownership. Optional inactive-scene
  presentation retirement is available but was not enabled in Toad after its
  cold-remeasurement tradeoff was measured.
- Opt-in subtree geometry reuse has a validated, configurable entry budget:
  `Compositor.max_subtree_geometry_entries` and
  `Screen.SUBTREE_GEOMETRY_CACHE_ENTRIES`. Zero disables it; the default64 is a
  heuristic, not a formal working-set bound.
- Inherited paint uses immutable data-only `PaintState` records. Style mutations
  and native topology changes own its validation epoch, avoiding repeated
  ancestor walks between mutations. Custom ancestry bypasses epoch reuse;
  ancestor collection and move/reset/merge/clear cases retain native behavior.
  The record uses NamedTuple to preserve Python3.9 compatibility.
- Footer consumes `Screen.active_bindings` through an immutable display
  projection. Repeated notifications coalesce; compatible native FooterKeys are
  updated/reordered rather than rebuilt. Reconciliation shares the native
  recompose transaction, checks retirement after awaits, and reschedules changed
  revisions. Keys still simulate native key events, so dispatch observes the
  current owner and keymap rather than a captured callback.

## Verification

Published checkpoint suite excluding snapshot tests: **3,412 passed, 1 skipped,
4 xfailed** with
`pytest tests --ignore=tests/snapshot_tests -q -n 2`.
Focused footer/scrollbar/opacity visual snapshots: **25 passed**. The companion
Toad pilot suite passed **52 cases** before the final transition regression and
NamedTuple compatibility cleanup; focused framework tests and the final full
framework suite cover those later changes.
The reactive lifetime fixture was also rerun after correcting its callback
closure construction: all five cases passed. Scoped Ruff and whitespace checks
pass. Tests cover weak publisher lifetime, live-watch preservation, real Footer
churn, lazy-storage independence, timer lifetime, cache generations, viewport
geometry/render parity, and class-scope invalidation after CSS edits.
Display-constraint tests cover independent reasons, CSS changes while hidden,
pre-mount restrictions, relative measurement, and native layout without CSS work.

The Toad branch contains the interaction runners, live profiler/DTO capture,
headless replay, source receipts, and evidence audit. Raw real-session captures
are private local artifacts, not repository fixtures.

## Still open

This checkpoint does not establish the target frame rate. The target is 16.7 ms
steady-state animation work at 60 Hz with responsive input during filtering and
loading. Whole-transcript/live-block scaling, remaining GC/render work, and
clean repeated real-terminal acceptance still need work. Passing correctness
tests or headless settlement is not proof of smooth UI performance.

The pre-async-activation native navigation workload completed83actions, including ten
tabs, resize, scrolling and selection. It still had a189.7ms maximum loop gap
and139.8ms GC pause; target-mode flush medians were696.2ms for opening and169.3ms
for switching. The four-thread/all-seven-filter run applied all52markers but
input acknowledgment still reached134.9ms. These are performance failures.

The subsequent Toad async-activation follow-up recorded loading-frame flush
median53.52/max62.59ms and switching median55.09/max105.18ms. Input/GC tails still
miss the universal sub50ms goal; see the companion Toad tracking plan for the
separate loading, final-shell and content-ready receipts.
