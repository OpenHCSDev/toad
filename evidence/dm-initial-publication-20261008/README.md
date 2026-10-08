# Initial message publication

Prepared conversation Markdown now acquires its original body worker during
mount, while the body message pump observes completion after mounting. Native
Markdown keeps its default complete-document mount promise (Textual #116).
There is no copied readiness state or new queue.

Source range acquisition joins the actual part publications. Viewport paging
honors its existing native frame receipt before choosing another source edge;
preview extents cannot repeatedly admit the remainder of the message.

The first matched run exposed excessive admission: 23 mounted parts, 568
widgets. Joining part workers alone did not solve it. After the frame receipt
correction, the run mounted four parts, 224 widgets; posting took 8.4 ms and an
actual App callback ran 0.73 ms later while preparation was pending. Preparation
still took 2.88 seconds. These are single source-App measurements, not physical
frame pacing or installed/live claims.

The existing paged nested-Markdown App control passed in 13.98 seconds:
posting 3.56 ms, body readiness 2.08 seconds, nested text and links, original
source copying, native scrolling/reversal, retirement and warm paint identity.
The redundant second update of the constructor's source was removed.

Raw measurements: `/home/ts/.cache/agent-scratch/dm-mount-frame-profile-20261008`.
App result: `/home/ts/.cache/agent-scratch/dm-mount-source-20261008`.
Earlier excessive-admission runs remain in `dm-mount-profile-20261008` and
`dm-mount-acquisition-profile-20261008`; none were overwritten.

Publication and installed acceptance follow through the existing frontend
publication owner. The backend and active native agent sessions are separate.

The candidate build passed all installed asset, origin and RECORD checks, but
the installed paged control timed out retiring the older body. The first source
run passed; this installed negative is not dismissed. Its receipt records a
LiveBody with 23 parts. A subsequent narrowed source run also failed, with no
viewport worker pending and a PresentedFrame with no deferred callbacks. The
frame wait now applies only to range admission, so it does not block retirement;
the remaining exposure/reader relation still needs its actual geometry trace.
The candidate is unpublished and the previous launch default is unchanged.
Raw failures remain in `dm-mount-installed-20261008` and
`dm-mount-retirement-source-20261008` under the owned scratch directory.
The added geometry trace (`dm-mount-geometry-source-20261008`) confirms the old
body is actually offscreen and not interaction-protected. The reader is at the
native bottom with follow intent, no anchor, no viewport worker and no deferred
frame callback. Retirement acquisition, rather than mistaken exposure or a
still-pending frame, is the remaining investigation.

The capture trace found nine missing hidden paragraph resources, with no lock,
stream or geometry barrier. The actual readiness handler notified the viewport
only for retirement capture; completing a visible paragraph did not resume a
viewport that had returned while awaiting its readiness. The registered body
now derives both visible and capture demand through the same viewport owner.
No new readiness flag, worker, queue or native geometry is introduced.

The corrected original App check passed in 14.04 seconds: post 4.95 ms,
readiness 2.15 seconds, exact source/link text, actual wheel/reversal/stop,
retirement and warm identity. Raw result is retained at
`/home/ts/.cache/agent-scratch/dm-visible-publication-wakeup-corrected-20261008`.
Two runner setup refusals occurred before App entry (missing pytest, then the
host native package taking precedence); neither invoked an application attempt.

The packaged successor at production head b6a0fe336 passed the same original
App check in 15.60 seconds: posting 3.26 ms, readiness 2.70 seconds, original
text/links/copy, wheel reversal and stop, native retirement and warm identity.
The command imported Toad and Textual from the candidate installation, not the
source checkouts. The helper receipt's historical source-scope label is unchanged;
this is installed App evidence, not physical terminal or saved SDK acceptance.
Raw result: `/home/ts/.cache/agent-scratch/dm-visible-installed-20261008`.
All 954 package assets, full 69 distributions and 2857 RECORD entries match.
The native wheel was reused exactly; only changed Toad was rebuilt.

## Cold eviction

The viewport previously captured complete paint for unadmitted live bodies and
then discarded it at budget trimming. ReleasedBody now distinguishes that
pending native-child release from CapturingBody. The existing budget supplies
admission, source custody owns pruning, and MeasuredBody retains the original
extent for later reconstruction. Visible/protected demand revokes cold release;
warm admission retains the complete capture requirement. No second queue/cache
or source store is added. MaterializingBody carries admission through its
original preceding resource. The shared retirement lifetime check replaces
repeated guards on the existing body owner.

The existing 32-body App control now crosses the original widget budget using
nine paragraphs per body, initializes the original private protocol, and waits
for its actual presentation/retirement. Its old Static-render copy expectation
was migrated to the existing native selection contract, also in the related
mounted-history control. Source Package AST: 288 modules, zero parse omissions.

Four bodies were observed cold-evicted without captured pixels, but the complete
lifecycle check is NOT qualified: the final run hit the original 12-second
settlement deadline. Earlier startup/count and placeholder-copy negatives are
retained. Raw runs: `dm-cold-eviction-{source,acquired-source,completion-source,
selection-source}-20261008` under `/home/ts/.cache/agent-scratch`, with logs in
`sidebar-drag-hotpath-20261007`. No deadline was raised or failure waived.

With the installed Native117 geometry scan, the next source App passed initial
retirement, cold reentry and selection preservation before encountering a stale
paragraph-tree expectation on repeated returns. Warm RenderedBody intentionally
has no paragraph children; the control now requires actual native visibility,
readiness and selectable retained text, or reconstructed cold paragraphs.
The following run failed at the earlier cold reentry readiness/tree assertion.
Thus completion remains unqualified; the next investigation is the actual
destination geometry and reconstruction demand, not a longer settlement wait.
Both App handles are terminal. Logs: `dm-cold-eviction-state-run.log` and
`dm-cold-warm-representation.log` in the same scratch directory. The first
state-capture invocation refused before App entry because its output directory
was absent; that setup failure is retained in `dm-cold-eviction-state.log`.

The completed current-navigation App run exited zero after cold reconstruction,
visible native selection and protected copy, repeated warm/cold returns, bounded
widget custody, resize, source append, anchor retirement and tab suspension.
The related selection consumers now acquire a paragraph from the original
clipped native cohort. The retirement control performs an actual extent change
before expecting layout completion; no-op transactions do not owe a reflow.
Tab navigation uses the current session owner instead of obsolete native modes.
All original assertions and deadlines remain, with retained-paint returns checked
through visible selectable text rather than compulsory native reconstruction.
Raw: `dm-cold-current-navigation.log` and `dm-cold-current-navigation-20261008/`
in the same scratch directory. Earlier failures are retained. Current complete
production AST: 288 modules, zero parse omissions. This is a source App result;
installed verification and publication follow separately.

Removing the parser prewarm barrier was also rejected: warm preparation was
1.99 seconds versus 1.80 in the baseline, with more live widgets at readiness.
Prewarming and native publication have distinct lifetimes; the original code
was restored. Raw: `dm-single-acquisition-profile-20261008`.

Installed delivery is complete for new launches. The build selects Toad
bc06324c6fbc2c6949a6293be8d490dc220d05a4, unchanged Native117 and retained
Core4baa; all954 assets/full69 distributions/2857 RECORD entries and native
package resources matched. The same lifecycle helper imported installed
packages with only tests on PYTHONPATH and exited zero. The original reviewed
frontend publisher changed only the toad default to
.artifacts/cold-body-delivery-20261008/runtime; backend defaults and existing
processes were preserved. Installed App checks do not establish physical frame
pacing or the software loaded in an already-open user window. Raw build,
installed and publication logs are cold-body-build.log, dm-cold-installed.log
and cold-body-publication.log in the same scratch directory.

## Installed physical wheel observation (incomplete)

The new private native seed produced a real saved response in isolated st, with
no provider errors. The first recorder composition exhausted its original
budget on unrelated sidebar resizing before wheel input. WheelCadenceJourney
now supplies shared history commands, and WheelWarmJourney reuses those commands
without recursively rerunning opening/chrome work. The original deadline and
input semantics remain; no product/package change was made by this correction.

The next new private capture completed upward scrolling, then exhausted that
same recording budget during the following gesture. The completed upward
segment has79 native writer intervals: median26.74ms, p9597.73ms, max317.44ms.
These are writer acknowledgments within checked driver-command bounds, not
monitor FPS or input-to-pixel latency. The driver trace has no semantic body
output events, so it cannot establish complete viewport readiness. The film also
shows table outlines disappearing while text remains; its source cause is not
proved. The native owner is tracing layout/capture and Parent owns body/source
currentness. No full scrolling acceptance or latency improvement is claimed.

Both original attempts are terminal; recorder and capture cleanup report no
remaining owned processes/errors. Each used one localhost request; the second
owner-usability input was unreached. Raw native journals and failures remain in
/home/ts/.cache/agent-scratch/dm-installed-wheel-20261008 and
/home/ts/.cache/agent-scratch/dm-installed-wheel-only-20261008. The second
unprofiled directory retains frame-delivery.json, scroll-travel.jsonl,
terminal.mp4 and wheel-up-partial-film.png. Existing user processes/defaults
were not changed by either measurement.

## Captured table geometry installed

The native layout now paints table keylines using the same acquired geometry
as its child cells. Offscreen capture previously combined new cell placements
with the last Resize size, which could be zero. Native held-root geometry
discovery also shares the original ancestry answers during each traversal;
it adds no persistent cache. Textual #118 and #119 are merged.

The candidate reuses the qualified cold-body Toad wheel and retained backend.
All 954 source/wheel assets, 69 distributions and 2857 installed RECORD rows
passed verification. The installed original retained-fragment App passed source,
style, resize, writer custody, warm reentry and disposal checks. The installed
native twelve-table App retained every offscreen table keyline without changing
published geometry or Resize state.

New Toad launches now use this candidate; running sessions remain unchanged.
The earlier physical upward-wheel measurement still has p95 writer intervals
of 97.73 ms and a 317.44 ms maximum. This publication does not claim those
stalls are resolved or that the incomplete physical journey passed.

Build, installed checks and publication logs are in
`/home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007/captured-table-*.log`.
Installed runtime and original publication result are in
`.artifacts/captured-table-geometry-delivery-20261008`.

## Auto-width preparation uses its parent assigned box

WorkerStatic now reads its parent's native-assigned inner width minus the
original scrollbar gutter. It no longer asks for screen position merely to
acquire width. Compositor owns that inner size and Screen supplies it through
the existing size/Resize publication. The child's own container_size is a
different box and is not substituted. Markdown, IRC and tool content inherit
the same implementation. Source/style/selection and resize reacquisition stay.

All 288 production modules parsed without omissions. The existing real App
geometry/source/style/selection control passed across three native resizes.
Matched 108-event raw-wheel headless profiles on the 3588-character source
measured request preparation 0.874s before and 0.066s after; native arrangements
fell from 259 to 160. These profiled runs include first-use lazy expansion and
have different frame/cohort counts. They do not establish physical latency or
identical steady-state paint workloads.

Profiles are in `wheel-owner-profile-20261008` and
`wheel-owner-assigned-width-20261008` under the existing sidebar scratch root.
Two diagnostic setup negatives (subclass CSS path and multiprocessing main
guard) remain recorded; they are not rendering or provider failures.

### Initial installed candidate result

The candidate passed full installed asset/origin/RECORD verification and the
three-resize source/style/selection check. Its paged-message journey timed out
reconstructing the older offscreen message after posting a following response.
The current installed predecessor fails the same check without the width
change. This is not evidence that the width change caused the failure, nor
proof that the affected paged path is qualified.

Failure-only diagnostics now record the complete awaited task chains and the
original native callback/mutation owners. The parent is waiting in
replace_range/join_part_publications under its source mutation while nested
Markdown workers await native mounting. Preparation callbacks remain held by
that mutation. The exact cycle and repair still need source ownership analysis;
the observed waits alone do not prove deadlock. No new package was published.

Original negatives and diagnostics are retained in
`assigned-parent-width-*.log`, `paged-body-wait.log` and
`paged-publication-wait.log` under the same scratch root, with private fixture
state in `dmnw3` through `dmnw8`. All those App attempts are terminal; none
submitted provider input. Previous writer interval statistics include the
100ms wheel input cadence and idle settlement; they do not alone prove a
317ms input-to-pixel stall.

### Independent width delivery and range ownership

The width-only change is merged in Toad #564 and published for new launches
through the original frontend publication owner. Its installed three-resize,
source/style/selection result passed; the separate paged negative also occurs
on the unchanged predecessor. That failure leaves reconstruction unqualified,
but does not block the independently verified width change. The existing
backend, native renderer and open sessions retain their original supply.
The installed source is `dcf85738`; current main has identical product bytes.
Publication is retained in `.artifacts/assigned-parent-width-delivery-20261008`.

PreparedContentRange no longer joins body writers in Mount, extend or replace.
This type owns native range membership; BodyMeasurement owns content writers
and WorkspaceScreen/DocumentViewport own paint readiness. The original frame
receipt still gates the next measured paging edge. Previously a mounted page
could await a child writer while its acquiring parent held the same window
mutation lock that the child's source publication needed. Both range users,
StreamingMarkdown and TranscriptPageView, now use the shared membership-only
implementation; the redundant join method and imports are deleted.

This range change is a separate unpublished branch checkpoint. The actual App
now reaches retirement, but does not complete the original warm-retention
check. `dmnw11` caught child shutdown waiting on native child tasks; `dmnw12`
caught runnable message/worker activity with the old body released. These are
different snapshots of unfinished work, not proof of a static native deadlock.
The native owner has both. The existing failure-only task diagnostic now sees
the original Python coroutine wrappers and native mount/exit child identities.
No new queue, timeout, readiness flag or callback exemption was introduced.

The complete source relation parsed 288 production, 417 test and 40 tool
modules without omissions. Original App negatives and private fixture state
`dmnw9` through `dmnw12` remain retained; no provider input was submitted.

Removing the source join entirely was insufficient: the profiled App exposed
a visible loading preview (`dmnw13`). The join is now owned by the existing
BodyMeasurement materialization worker, after its source operation returns and
releases the window mutation fence. Range Mount still owns membership only.
The following App observation (`dmnw14`) has no mutation roots while the parent
joins original nested body publications; it still times out awaiting native
mounting. Neither observation is a successful full paged acceptance. The
profile cannot explain retirement cost because it failed at the earlier paint
assertion, and profiling overhead prevents direct timing comparison.

## Retained paint admission and completed source App

The viewport used the last materialized widget count to decide whether to
retain message paint. That conflated compact retained rows with a disposable
native tree, discarded useful paint before retirement, and let lookahead
rebuild hidden controls. PresentationBudget now admits paint by the original
message count and actual source/row bytes; native lookahead keeps its original
widget budget. DocumentViewport derives both orders from its existing owners
and warm chronology, with no second stored admission policy. Session/sidebar
native tree budgets are unchanged.

The original paged nested-Markdown App passed (12.29 s): 24 sections, Unicode,
nested text, links and copying, wheel reversal/stop, native retirement and
return to the same retained paint resource. Posting was 5.077 ms; readiness
1.8007 s. This is source App evidence, not physical frame-time evidence.
The bounded runway App has no stationary restore/retire/reconcile calls,
no further evictions, and 48 native widgets against its 60-widget limit. Its
fixture now selects a genuinely retired tree, not never-materialized source;
content-cost invalidation and resize checks pass. The original cold-body App
also passes source/selection, cold restoration, scroll/resize/live-update,
mutation-anchor retirement and session suspension.

Raw logs are in /home/ts/.cache/agent-scratch/sidebar-drag-hotpath-20261007:
paint-admission-app.log, paint-admission-bounds-corrected.log and
paint-admission-cold-app.log. Earlier negatives remain preserved, including
the original bounded fixture selection and missing output-directory refusal.
No provider input was sent. Installed verification and publication follow.
