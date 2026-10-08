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

## Installed candidate and remaining cold navigation gap

Candidate706341498 installed assets/RECORDs/full69 and unchanged native
supply verified. The original paged App passes on the installed wheel
(15.22 s; post5.136 ms, readiness3.117 s) and the bounded runway App passes.
The installed cold lifecycle fails at its first target return: the chosen
message is RenderedBody/ready with no children, but is outside the viewport
(region y=-67,height38; scroll/target70). The source run had returned that
message visibly as LiveBody with paragraphs. These differing observations
do not establish a sole cause. The candidate is not published as the new
default; the current width default remains. Raw installed lifetime failure
and cold-destination.json are retained; no retries or bounds were changed.
Parent owns the actual cold navigation/anchor relation next.

## Reader source identity checkpoint

Original cold navigation selected scroll0; later paragraph compensation
moved it to56 while preserving a paragraph whose source offset changed16→72.
The trace does not establish which message owned that paragraph. Selecting
only ready paint can choose a later source point while the original paragraph
is still wrapping. HistoryWindow now chooses the visible original message
first, then an exposed source within that message regardless of paint
readiness. Foreground and lookahead body restoration now share reader_anchor
instead of independently selecting the first visible body. Tail/interaction
custody and native placement compensation are unchanged.

This coherent ownership change is not full cold acceptance. The original
cold App now reaches repeated returns but still loses index4 (RenderedBody
rows38, scroll/target163, no exposed/published native placement).
shared-reader-cold/cold-return-unexposed.json retains the exact observation.
Native producer owner is reviewing committed/query geometry supply; Parent
retains Toad ownership. Original cold assertions and bounds are unchanged.
The initial full-operation profile timed out before navigation and is an
observation limit; the later acquisition-scoped trace reached the failure.
Complete HEAD source AST288/417/40 parsed with zero omissions, all anchor
writers and consumers inspected; current changed modules also compile.

## Native contract and corrected source-navigation consumer

Native review found no projection omission: scroll_to_widget makes one
least-distance move, not a persistent source destination across later worker
reflows. Acquired target4 y205 was correct; surrounding source extent then
changed. All55 recorded native captures matched BodyMeasurement dimensions.
The four qualifier navigation callers now bind the existing preserve_reader
lifetime while the actual source/restoration settles. No visibility, source,
selection, bounded-tree or timing assertion was weakened. The complete cold
App passes with the unchanged original anchor-rebind semantics. A speculative
rebind-to-visible-source edit was removed, without entering the build.

The existing tail-transition control fails identically (-161 then0) on the
unchanged installed width predecessor and the candidate source. It does not
block the independently verified DM change or establish a new regression.
Parent retains that separate publication-observer/source-transition trace;
there is no full-history or physical saved-session acceptance claim.
Final source raw: bound-reader-final-source.log. Tail negatives:
predecessor-tail-anchor.log and bound-reader-confirmation.log.

Followthrough: the tail control now reads its marker from the actual native
ChopsUpdate/LayoutUpdate cells rather than sampling current DOM geometry during
unrelated publication. Its expected reader destination derives from the original
anchor geometry and scroll intent; held paint is not that destination. The
published installed build passes this corrected tail/reader control, including
the original forbidden tail geometry reads. No production change or timing
waiver. Raw published-tail-observation.log retains the intermediate overly broad
damage observation failure; published-tail-cells.log records the actual-cell pass.
Physical saved-session frame time remains unverified.

Installed physical followthrough: the merged Core launcher correction aedccdd86
was absent from /home/ts/bin/toad-comms. Installed its exact original source;
default frontend selection now follows published Toad independently of backend
Python, while explicit runtime overrides remain matched. Prior launcher bytes
are retained in sidebar-drag-hotpath-20261007/toad-comms-before-frontend-selection.sh.
One existing-owner, zero-submission wheel_cadence capture completed on isolated
plain st, using the actual default DM frontend and original backend. Evidence:
/home/ts/.cache/agent-scratch/dm-owned-reader-wheel-physical-20261008/receipt.json,
terminal.mp4, wheel-up-motion.png, scroll-travel.jsonl and frame-delivery.json.
All recorded owned processes retired without cleanup errors. Sampled up-motion
cells show original message text, without preview placeholders. This is not a
complete frame-pacing pass: median enqueue-to-writer 2.54ms/p95 16.18ms, but native
writer intervals include idle/nonbody frames and cannot establish smoothness.
The original source-bound body observer recorded no body outputs for these saved
message rows; its scope must be resolved before claiming useful-body latency.

Motion correlation: each physical 36-packet gesture produced 36 original
nonrestoration scroll updates; the worst final-scroll delay after input submission
was 8.34ms. Next-writer completion from those scroll updates had median about
8ms and worst47.28ms. That is writer acknowledgement, not pixel input latency.

Fast active-channel check remains FAILED against the requested responsiveness:
160 wheel packets at5ms spacing, three reversals,20 incoming messages/16 private
recipients, actual installed App/native Driver. Wheel handling median76.1ms,
p95278.3ms/max348.8ms; UI-loop max82.5ms, four gaps over50ms. Final queue drain
3.49ms does not erase the in-burst lag. All packets remained ordered. Raw:
sidebar-drag-hotpath-20261007/dm-owned-reader-active-wheel-visible-20261008/result.json.
The original helper timeout is preserved in dm-owned-reader-active-wheel.log;
it demanded extent readiness for every mounted row before any input. The corrected
helper requires the actual visible row cohort to be ready, with the original
30s bound and input workload unchanged. Both App handles are terminal, provider0.
Parent owns the remaining active-channel publication/dispatch cost trace.

## Compact native-content preparation

IRCMessageSource already produces native Content, including symbolic styles,
sender/target actions, URLs and authoritative mention spans. Its old RichSource
base converted that Content to Rich Text and wrapped it through a second
renderer. It now inherits the existing NativeContentSource implementation used
by plain/ANSI tool output. Formatting remains in the worker; native wrapping,
selection/source coordinates and strip metadata use that original owner.
No widget, cache, codec or preparation queue was added.

The full current src/tests/tools AST pass parsed 745 modules without omissions;
all source construction and style consumers were inspected. The existing actual
IRC App passed full-width wrapping at 80/36/120 columns, sender/target clicks,
keyboard navigation and style-only no-layout publication. Its original control
now also checks native select-all/copy preserves the complete source text.
Raw: sidebar-drag-hotpath-20261007/dm-native-content-wrap-selection.log.

The same private active-channel workload completed with this Toad source and
the integrated owner-presentation Core source: wheel median24.0ms/p95195.5ms,
maximum225.0ms; largest UI-loop gap84.1ms. This is one source-App run, not an
installed/live or causal speedup claim. The workload still fails the requested
frame pacing; all 160 wheel packets were ordered, 20 incoming messages were
published and provider inputs were zero. Raw:
sidebar-drag-hotpath-20261007/dm-native-content-wheel-20261008/result.json.

The successor wheel passed its original IRC control and all 954 installed
assets/69 packages/2857 RECORD entries. Toad #566 merged; the original reviewed
frontend publisher installed the new default without changing backend owners.
Installed burst result: median3.1ms/p95107.7ms/max231.2ms, UI-loop max77.0ms;
still not a frame-pacing pass. Raw dm-native-content-installed-wrap.log and
dm-native-content-installed-wheel-20261008/result.json.

The actual default-launch physical channel check stopped before opening the
channel: Ctrl+B did not reveal Channels, so the exact channel had no native
click resource. Original owner was preserved and recorder cleanup has no
remaining owned processes/errors. Raw/video remain at
/home/ts/.cache/agent-scratch/dm-native-content-channel-physical-20261008/.

Source establishes the wrong owner: MainScreen.check_action queried inside a
logical session for ChannelsSidebar, which now belongs to WorkspaceScreen.
The single binding, availability decision and reveal action move to that
workspace, deleting the Main/Comms copies. Existing current-selection App now
checks real Ctrl+B from both agent and channel input; it passes unchanged
cross-sidebar destination, Ctrl/Shift selection, theme/hover and date checks.
The first authored check directly changed collapsed while leaving canonical
settings unchanged; corrected setup uses the original toggle owner instead.
Both raws are retained; no production fallback or timing increase.

The shared reveal and Core acquired-owner presentation are merged and installed
for new frontend launches. The second physical check actually revealed Channels,
but no channel rows were visible and the exact #comms target was unavailable.
Physical acceptance remains incomplete. Its existing owner was not restarted;
the recorder joined all owned children. Raw/video: dm-native-content-channel-physical02-20261008.

The installed original App captured six live channels/31 thread rows and
published them successfully, both without ACP and with the exact original ACP
attachment. These observations contradict a consistently empty backend result;
they do not establish why the earlier physical publication failed.

Source nevertheless establishes a retry defect: observation recorded a revision
before native publication completed, while interrupted rebuild clears its
snapshot. The shortcut could then suppress every same-revision retry. Commit
the observation identity only after the original projection retains that exact
snapshot; the shortcut also requires a snapshot. Existing native logger now
reports caught errors rather than silently hiding them. No new retry queue,
timer, cache, timeout or public input. Complete source parse: 288 production,
417 tests,40 tools, zero omissions. Existing sidebar current-selection App passes.
Raw: sidebar-published-revision-control.log, live-sidebar-publication.log and
live-sidebar-acp-publication.log. A custom recorder diagnostic command was
refused before launch by the original existing-thread target contract; retained
physical-sidebar-publication-diagnostic.log records that refusal.

Toad #568 merged. The reviewed installed frontend passed the same actual
current-selection App and all954 assets/full69/2857 RECORD entries; the original
publisher installed it for new launches without backend changes or owner restart.
Its physical existing-thread journey completed: Ctrl+B roster reveal, actual
#comms tab open and both member-disclosure clicks. Final screenshot shows the
channel text and real roster. Original owner identity remained alive and unchanged;
all recorder-owned processes joined with no cleanup errors. No inputs submitted.
Raw/video: sidebar-publication-retry-physical-20261008; existing Textual log:
sidebar-publication-physical-textual.log. No caught sidebar error occurred in
this run. The source retry defect is repaired, but the initiating cause of the
earlier empty roster remains unrecorded; this single working path does not
establish that cause or smooth active-scroll performance. Footage performance
review remains separate from the observed channel/disclosure behavior.

One targeted installed active-wheel measurement separated elapsed time from
the UI thread's own CPU, using the unchanged original private workload. The
worst Screen._refresh_layout call was46.69ms elapsed/45.90ms UI CPU; worst timer
admission48.41/47.02ms. This call includes native reflow, resize watchers, paint,
display/hit updates and synchronous layout-signal subscribers, not arrangement
alone. The run still fails pacing: p95 wheel290.80ms/max319.31ms; largest loop
gap85.77ms. All160 packets remained ordered and20 incoming updates completed,
with no provider input and joined original fixture cleanup. Attribution raw:
sidebar-drag-hotpath-20261007/wheel-ui-cpu-attribution-20261008/ui-cpu.json.

This rules out treating worker-thread GIL contention as the complete explanation
for these synchronous admissions. Existing channel reads capture live Comms and
source objects on their joined thread lifetime; these cannot be moved by pickling
live services/SQL handles into the pure renderer. Native source review confirms
existing arrangement reuse and spatial culling; no further traversal deletion
was justified. Remaining work is the original row measurement/publication and
paint family; no speculative cache, process adapter or weaker readiness added.

## Notification disclosure simplification

`MessageNotifications` keeps its original notification tuple/error and native
Collapsible. Its details Static is acquired only by expansion or explicit
existing details access. Closed status updates update the summary but do not
format or refresh hidden recipient text. Once acquired, the same body survives
collapse and is refreshed from the current original outcome on reopening.
No second status store, cache, polling task or disclosure implementation.

Source consumers: all705 src/tests modules parsed with zero omissions; seven
notification details reads, no external writes. Existing explicit reads remain
supported, including before mount. Changed module compiles; diff check passes.
Real native App/Pilot disclosure check passed: no collapsed child,48 recipient
summary, actual title clicks, live unavailable result, deferred closed updates,
current empty result on reopen and one retained body. The authored check first
passed an unsupported constructor id; it refused before widget mounting. Its
original bytes are retained, then only that fixture call was corrected.
Raw check: /home/ts/.cache/agent-scratch/dm-notification-disclosure-20261008/source-disclosure.log.
This is disclosure behavior evidence, not a frame-time or full DM acceptance.

Installed and delivered: PR569 merged. The original durable frontend publisher
now selects `.artifacts/dm-notification-disclosure-delivery-20261008/runtime`
for new Toad launches. Original Core09a/nativeb486 wheels reused byte-exact;
954 source/wheel assets,69 packages and2857 RECORD entries verified. Backend
defaults and running owners remain unchanged; existing windows keep their
loaded code. Publication receipt: `live-publication.json` in that directory.
The same native disclosure check passed using installed imports.
Original private wire/native Driver workload passed ordered160 wheel packets,
20 incoming messages and16 recipients with no provider inputs; all owned
handles terminal. Pacing remains FAIL: wheel p95159.1ms/max229.2ms,
UI-loop max125.9ms and published-frame p95104.9ms/max184.0ms. This noisy
single run does not establish a speedup. Remaining synchronous native layout,
measurement and publication cost must still be removed through its owners.
Raw installed results/publication under
`/home/ts/.cache/agent-scratch/dm-notification-disclosure-20261008/`.

## Prepared dimensions and paint rules

Original UI-thread clocks now separate native reflow, paint and layout signal
subscribers. Worst observed reflow used30.16ms UI CPU; visible-only reflow4.33ms,
paint3.86ms, subscribers1.64ms. This measures those synchronous scopes, not
exclusive child costs or all wheel delay. Raw: existing scratch
`wheel-ui-native-spans-20261008/{ui-cpu,native-spans,result}.json`.
The earlier cProfile collectors still mix worker code into their timings, even
after depth correction; their cumulative rankings cannot establish UI cost.

WorkerStatic's acquired measurements read original prepared width/lines, not
live paint styles. Its inherited Static rule sensitivity nevertheless treated
it as an unknown live renderer and retired geometry on paint-only updates.
The existing native rule hook now derives sensitivity from acquisition: keep
the conservative Static path before acquisition; afterward the worker result
owns dimension changes. notify_style_update still requests the styled result;
its existing publication invalidates layout when width/line count changes.
No second dimensions store or cache. Native box/layout rules remain native.

Complete Toad/native production parse538 files,0 omissions;12 resolved worker
family classes, including generated Markdown blocks, select original worker
width/height methods. All745 Toad modules parse; both changed modules compile.
Existing parent-height/source and geometry/style/selection controls passed
2/7.82s, including real process preparation,3 resizes, painted color,selection
and copy/source updates. The color change preserves the measured epoch.
First harness used stdin, which process spawn cannot reopen; raw refusal is
retained. Corrected only the runner to a persistent original main-guarded file.
Unknown runtime replacement of declared methods remains outside this claim.
Raw: `/home/ts/.cache/agent-scratch/prepared-style-measurement-20261008/`.


PR570 merged; its candidate installed controls passed2/8.31s. The candidate
is NOT the live default: publication is held by the affected scroll result.
Candidate original native wheel run: median267.6ms/p95471.3ms/max499.0ms;
unchanged currently installed cohort comparison:4.2/204.0/237.4ms. Both have
large frame gaps and all packets ordered. Candidate source run had median8.1ms,
so one installed comparison does not prove a sole causal regression, but it
cannot be waved away to publish a performance improvement. Candidate and
unchanged raw deliveries,frames,scroll positions and loop gaps are retained.
Current default remains dm-notification-disclosure-delivery-20261008/runtime.
Candidate: prepared-style-measurement-delivery-20261008/runtime; verified954
assets/full69/2857 RECORDs and unchanged Core/native supply. No public inputs.
Original native review confirms sibling row measurement epochs are not retired
by an unrelated row mutation: ancestry invalidation stops at its real fixed-size
boundary. Changed vertical membership still requires cumulative placement;
there is no supported blanket native invalidation deletion. Next investigation
is delayed original pointer completion and page-admission timing using the
captured packet/scroll relation, alongside measured synchronous reflow cost.


### Original pointer wait versus mount acquisition

Dispatch observation records original native queues without changing delivery:
App MouseScrollUp247.8ms; MountedMessageHistory Callback219.38ms (update_styles
plus original next-callback flush); overlapping IRCMessage Compose188–208ms.
These are wall durations including waits, not exclusive CPU or style cost.
Source: Widget.mount registers children, posts update_styles and schedules the
same AwaitMount with call_next. MessagePump._dispatch_message then awaits its
next callbacks before completing the parent dispatch. AwaitMount waits every
original child mounted event under its completion lock, then refreshes parent
layout/mouse geometry. Wheel delivery awaits original routed/bubbled queues,
including this mounted-history parent. Thus unrelated new-child acquisition can
hold existing viewport input despite a responsive asyncio loop.
No wheel bypass or reordering is justified. Native owner Arendt owns moving
optional mount completion through its original lifetime without blocking the
parent input queue, preserving explicit awaits, unawaited mounts, errors,
layout/mouse currentness and cancellation. Parent remains Toad writer.
Raw: prepared-style-measurement-20261008/candidate-dispatch-waits/
(dispatch-waits.json,ui-cpu.json,result.json). Same original private fixture,
160 ordered wheel packets,20 updates/16 recipients,0provider; handle terminal.
Prepared-style candidate publication remains held; current default unchanged.


## Document wheel routing

DM and channel histories already select the same compact IRCMessage by default.
The optional Markdown row has distinct full Markdown behavior; it is not the
default DM renderer. Lazy notification details are in the published frontend.

The native mount-completion candidate removes the history actor callback join
(previously 219 ms). Its installed private-driver observation still has slow
frames: wheel median 92.55 ms / p95 288.81 ms; frame p95 106.1 ms. This is a
targeted queue repair, not an overall pacing pass.

At a reached viewport edge, native generic wheel bubbling continued through
workspace ancestors that cannot scroll the document. HistoryWindow now ends
that route after the original native movement/clamping. Nested controls still
receive input first. Explicit super delegation prevents the native MRO dispatcher
from invoking the base movement twice.

The actual private Toad App control passed: one native movement, stopped clamped
edge events, and independent nested scrolling. Raw control and earlier fixture
refusals are retained under
`/home/ts/.cache/agent-scratch/prepared-style-measurement-20261008/document-wheel-boundary-controls/`.
The preceding burst observation retained ordered 160 wheel packets and 20
incoming messages; its route ended at Window. That source observation also
included the merged prepared-style rule and preceded the final single-dispatch
correction, so its aggregate timings are not a causal measurement of this patch.
Neither this viewport change nor the native mount candidate is published live.


## Published document wheel / native mount integration

Textual120 and Toad571 merged. Matched published frontend: Toad fbb8e395d,
Textual c330608250, unchanged Core client09a0131ab. Full954assets /69packages /
2857RECORD entries and retained native Pi matched.

Actual installed private-driver observation preserved160 ordered wheel packets,
three reversals and20 incoming messages /16recipients, provider0. Wheel median
3.88ms/p95 78.80/max219.98; backlog after final post3.86ms. Frame p95 109.87ms/
max337.05; loop max105.21. Overall pacing still FAIL, not a statistical speedup
claim. Timer update reached61.32ms UI CPU; layout48.81ms UI CPU.

Installed real-click disclosure passed: no closed body, opened body current, live
error, closed update deferred, reopen current, original pre-mount explicit read.
Reviewed frontend publisher changed NEW launches only; backend defaults, active
route and native package preserved. Existing windows keep imported modules.
Receipt: `.artifacts/document-wheel-routing-delivery-20261008/live-publication.json`.
Raw build/App/disclosure/publication files remain in
`/home/ts/.cache/agent-scratch/prepared-style-measurement-20261008/`.

Removed55,187,908bytes of superseded never-published native-mount candidate
runtime after fresh privileged census226processes/no gaps/no refs and separate
default/publication checks. Wheels/source/proofs/raw and actual published/rollback
runtimes retained. The first evidence append met absent sparse-checkout path;
no evidence was changed then. Materialized original HEAD bytes and appended here.

Next work is original synchronous geometry/layout and paint publication; native
capture/FIFO is preserved rather than bypassed to mask its costs.


## Wire row resources owned by composition

WireMarkdownMessage and IRCMessage now retain the actual body and notification
widgets created by their original compose methods. Recomposition acquires fresh
resources; unmounted resources cannot supply read/extent evidence. Compact and
full Markdown remain distinct rendering contracts. CommsChatView uses the row's
notification resource, revalidating attachment after the asynchronous read.
Three body queries and the per-row notification descendant query are deleted.
No message, read ledger, status or preparation result is copied.

AST:288 production/417 authored modules parsed, zero omissions. All changed row
family body/feedback selector calls are gone. The separate incoming/outgoing
transcript WireMessageHandling queries belong to another declared resource
family; this change does not claim to replace them.

Existing real private wire partial-paint control passed: only painted bodies
acknowledged, scrolling admits the remaining original page and compact/Markdown
style replacement preserves identities/read results. Actual private Toad App
resource control passed: both styles own their mounted children, recomposition
replaces retired instances and removed bodies cannot authorize reads. First
resource fixture used a bare Screen without the real history viewport and failed
its Markdown admission; preserved, then corrected to the real wire/window.
No production fallback or timeout changed.

Raw/source control files are under
`/home/ts/.cache/agent-scratch/dm-owned-resources-20261008/`. Speed improvement is
unmeasured. The next required installed observation also retains Layout.widget
identity and original node/layout source epochs in the existing recorder so
native work can distinguish real changed extents from repeated late requests.


## Row-resource frontend delivered

Toad572 merged. Built exact Toad31fe7bd25 with unchanged nativec330/Core09a.
Full954 assets/69packages/2857RECORD entries/native package matched. Installed
real wire/Toad resource control passed for compact and Markdown: composition
owns children, recomposition replaces retired instances, removed bodies cannot
authorize reads. Source partial-paint control passed with original durable reads.

Installed original burst:160 ordered wheel packets/20incoming/16recipients,
provider0. Median4.72ms/p95220.87/max259.54 input, final backlog10.48ms; frame
p95109.43/max212.56; loop max124.10ms. No reliable speed gain established.
Repeated queries are removed, but pacing still FAIL.

New diagnostic identifies253 Layout sources:48CommsRow,43CollapsibleTitle,
40MessageNotifications,40Contents,40IRCMessage,11IRCMessageText,10Window,
remaining navigation widgets17. No identical identity+node/layout-epoch repeats.
Four CommsRow instances each submitted12requests with layout epochs increasing
by2. Their original paint_thread_frame already calls update(Content,layout=False);
source declarations match native Static measurement/rendering and original box
hooks. The exact producer of those epoch changes still needs proof. Native owner
received actual source-bearing raw; requests are not being silently discarded.

The original reviewed frontend publisher selected this runtime for new launches,
preserving backend defaults, active route, original native and running owners.
Receipt: `.artifacts/dm-owned-resources-delivery-20261008/live-publication.json`.
Source/build/installed/publication raw are retained in
`/home/ts/.cache/agent-scratch/dm-owned-resources-20261008/`. Existing user windows
keep imported modules. Goal remains open for frame pacing and full user workflows.


## Channel header has one presentation owner

Source trace proves the paired channel-row layout epochs: SidebarProjection
first wrote pin/name without counts, then ChannelGroup.present wrote name/counts
without pin. Even identical final sources therefore changed the displayed text
twice. The second write also erased the visible pin marker.

Deleted the first writer. Existing ChannelGroup.present now supplies pin/name/
active/registered counts once under original member custody. Its row's original
Static content equality handles unchanged text. No new state/cache or suppressed
layout request. Actual source changes still use native update/layout.

Before/after AST705 source/test modules parsed with zero omissions; all channel
header label publication now comes from ChannelGroup.present. Existing real
private-store/native-App activity-order control extended in place and passed:
pinned channel label/counts survive, rebuilding an unchanged snapshot leaves
the header layout epoch unchanged, changed activity still reorders members,
original widget identities/pins and unchanged prepared resource preserved.
Raw: `/home/ts/.cache/agent-scratch/channel-label-owner-20261008/source-app.log`.
Installed latency remains to be measured; no broad pacing pass claimed.
