# PR239 retained physical profile: foreground publication and resource work

Owner: Kepler221/239 tools and analysis. Production owner: Heisenberg239.
No source in Heisenberg's worktree was changed. No application, native prompt,
provider, profiler or capture was started. Initial interrupted-process audit
found no remaining owned recorder/ffmpeg/py-spy process. Cold peer first paint
from attempt03 remains failed; earlier raw and receipts remain immutable.

## Evidence boundary

Original physical83.02-second attempt03:
`/home/ts/.cache/agent-scratch/toad-workspace-warm-236-20260930-attempt03/capture`.
Recorded production479e8783/Core4295d680/Textual2e49cb83/nativee36. All source
line references below refer to this installed source, not subsequent PR239 edits.
The same-run trace contains879 GIL samples, one sampling error and nominal
video/trace clock uncertainty±74ms. Kernel deltas show held UI CPU around80–84%
and stationary10%; changed Chrome stack groups cannot apportion that CPU.

Two retained reports use the existing ProfileTrace decoder, not another parser:

- `physical239-restore-layout-stack-review-20260930.json`: explicit queries for
  restoration, recomposition, layout, style replacement, render worker execution
  and inactive-paint retirement across scroll and tab phases.
- `physical239-viewport-request-stack-review-20260930.json`: complete sampled
  viewport-body caller chains, preserving process/thread identity and phase clocks.

The recorder preview was capped at20 frames. These reports include all matching
frame identities with bounded full-stack examples, phase physical artifacts and
kernel CPU totals. They are reusable through `tests/tools/profile_trace.py`.
The query selects source/function declarations supplied by the caller; it owns
no second registry of production mechanisms. Unknown phases and overwritten
reports are refused. This follows BOUND-1 (decode once) and MEMB-1 (no duplicate
owner roster) rather than creating another analysis pipeline.

## Concrete observed relationships

| Phase | Observed changed stacks | Stacks matching queried mechanisms | `_arrange_root` presence |
| --- | --- | --- | --- |
| Held Up |98|51|27|
| Held Down |110|65|39|
| Reverse Up |87|50|20|
| End stationary |28|1|1|
| Return A |46|18|6|

These are observed changed-stack groups, **not** invocation counts, proportions
of CPU, samples or durations. `_refresh_layout` occurs at several frame/line
identities in a stack; summing those identities would overcount even group
presence, so no such summed layout total is presented.

1. At video38.786s, a native fragment's `on_mount`(transcript_history191) enters
   DocumentViewport.register202 → request236 → Worker._start416 →
   `_reconcile`322. At38.676s, a native scroll animator enters the same request
   and reconciliation path. Other groups show ordinary key action/scroll and
   mount registration entering DOM traversal and owner-ancestor filtering.
2. In recorded DocumentViewport source, `_reconcile` rebuilds root order by
   walking the window tree and checking ancestors321–323, expands every selected
   root's descendants344–348, evaluates recursive readiness, and measures the
   warm set through `_trim_warm`353. Native eager worker launch allows this
   synchronous work before the next await. The existing one-pass trim avoids the
   previously removed quadratic survivor recount, but the one-pass measurement
   still occurs each reconciliation and after each background restoration396.
   Repeated traversal is a concrete investigation lead, not yet proof that an
   observation was unnecessary or that a new cached registry should replace it.
3. Recorded TranscriptFragmentView preparation dispatches pure render tasks to
   existing background workers. Restoration still calls native recompose,
   mounts child widgets, applies stylesheet rules and requests layout. Retiring
   the body removes children and requests layout. In the same trace, recomposition
   and mount chains reach native stylesheet.replace_rules. Consequently prepared
   syntax/token output alone cannot eliminate native tree/style/layout publication
   work or certify retained raster/Strip reuse. Existing mounted resources and
   their native invalidation/lifetime owner are the required crossing.
4. Down-phase native layout/compositor stacks and reverse-phase traversal align
   with the already inspected readable physical scroll progression. There are
   no sampled `_restore_body` or `restore_body` matches for these queried phases;
   asynchronous sampling can omit awaited parents, so restoration cannot be
   excluded or declared the dominant cost from this trace. Render worker
   execute_render_task is observed in Return A, separate from UI layout; that
   interval also contains the cold peer finishing in the background, so it is
   not attributable to warm A return alone.
5. No queried inactive-paint retirement/release match supports a logical-tab
   attribution. Heisenberg's source trace confirms logical A/B/A shares one
   WorkspaceScreen: its screen-stack suspension hook is not each logical source
   retirement. Heisenberg corrected that initial lead before editing. Logical
   source display/visibility and layout publication need their own exact consumer
   analysis; this report does not justify changing an inactive-screen override.

## Scope and next action

Heisenberg retains production reconciliation/runway/restore/publication claims;
Sch's native source/restore seam is not edited by this tools checkpoint. Mendel450
backend and Arendt452 configuration work are independent. Use this source/profile
crossing to reduce repeated native traversal or tree/style publication through
the existing resource owner, preserving layout compensation and original history.
No timer, scheduler, proof cache, semantic mirror or competing worker registry is
proposed. Actual matched-candidate footage is warranted only after a meaningful
production change; no unchanged run is requested here.

Verification of the tools is analysis of the same actual retained trace plus
Python compilation/diff checks. Full phase stacks and kernel/physical links are
generated by the reusable reader; original raw checksums are retained unchanged.
Implementation deletion count:0 (86 lines extend the existing reader/CLI).
This checkpoint is an analysis capability and source-backed handoff, not an
installed product/performance readiness claim. Capacity did not recur in this
continuation; the configured model remained unchanged.
