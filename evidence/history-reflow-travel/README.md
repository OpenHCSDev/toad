# Native reflow is reader restoration, not new input

Owner Heisenberg, original PR254. Contributor Kepler PR260 owns only the existing
MovingPreparation.edges direction hook; its whole source and proof normally
integrated at 7475f34e. No publication, Conversation or native ingress edits here.

## Original source relation and counter

Actual ToadApp, WorkspaceScreen, HistoryWindow, native Textual message pumps,
compositor and three saved TranscriptHistory resources. No fake Agent/viewport,
ACP child, provider, input, public root read/write, or owner restart. A private
Comms root is initialized inside persistent owned evidence scratch. Original
AssistantTranscript pages use native rendering and mounting. The small body
cohort is deliberately retained to isolate reflow from separate budget eviction.

Removing the first real saved page while retaining the third page reader changes
native extent. Baseline native reflow clamps scroll_y 254 -> 230 outside the
original restoration scope; only the later 230 -> 127 source compensation is
inside it. DocumentViewport.request observes that clamp as travel. Its moving
velocity changes -534.003 -> -255.312 with zero user input. The native marker
still looks stationary, so checking only final paint or demand identity misses
the error: same-direction MovingPreparation mutates its velocity in place.

The existing WindowRestoration ancestor now owns a nestable geometry context.
Workspace enters it before native reflow and retains it through source offset
compensation and any second reflow. Final geometry rebases the existing
DirectionalPreparation position; original velocity/direction/expiry are kept.
Standalone ReaderPosition/HistoryAnchor restore callers inherit the same scope.
No new flags, cursor, timer, cache, registry, retry, semantic mirror or clamp.

Candidate: both original 254 -> 230 -> 127 changes occur inside restoration;
marker y=3 and reader revision=4 stay unchanged. The original moving velocity
-515 remains -515 and later actual requests sample no motion. Two source history
resources survive; Agent is unbound. Exact integrated source counter exits0.

Command (serial, <35s bound):
REFLOW_TRAVEL_EVIDENCE="$PWD/.artifacts/reflow-travel-integrated01" \
PYTHONPATH="$PWD/src" timeout 35 \
/home/ts/.local/share/agent-comms/runtime-source-publication-custody-20260930/bin/python \
tests/history_reflow_travel_pilot.py

Frozen dependencies Core970/Textual6b/SDK0.12.1; owned source imports only,
not an installed candidate. Native 41MB physical/sign-flip evidence remains in
Kepler's protected retained-history-buffer-260-20261001-directional01 capture.
That 434-change trace motivated the counter, but the specific held-direction
flips are not claimed fixed physically until one changed candidate journey.
No total CPU/firstpaint/continuous scroll/default readiness claim.

## Closure and ownership

WindowRestoration.restore is inherited by ReaderPosition (Tail/Offset) and
HistoryAnchor (Tail/Record). Its consumers are HistoryWindow.restore_history_layout,
WorkspaceScreen._refresh_layout and TranscriptPresentation.painted ReaderPosition
application. No member roster or duplicated policy is added; a new restoration
case only implements _restore and inherits geometry custody (IMPL-4/IMPL-13).
The original native _restoring resource scope is reused, not a source-state copy
(IDEN-5, TIME-1). Two production files:17 added/5 deleted. Bounded per-file
measures unchanged except code_lines +3/+6. All remaining full254 plans preserved.

## Completed physical source checkpoint and whole-window continuation

Physical source production2f22cd39 (normal main/docs integration a054c59a,
ZERO production difference) completed65.281176s in one existing SourceCapture.
Raw protected path:
/home/ts/.cache/agent-scratch/history-reflow-254-20261001-candidate01
Actual isolated st/LinuxDriver, held Up4s/Down4s/reverse4s, End and15idle,
714 GIL samples/0errors. Exact native journal41,270,331B SHAfc5a6209 remains
unchanged; no public root read, provider, native input or owner starts. Runtime
selection unchanged and recorder/caller cleanup[]/0. Encoder255 is retained
normal SIGINT completion, not a claimed application exit status.

Personally inspected Down/reverse/idle PNGs: body readable. The original end
marker is BEFORE End key by ScrollJourney.actions; final idle native y107=max107,
follows_tail=True, stationary demand and no pending work.145 widgets<=320 and
111466 source bytes<=64MiB. Whole Kepler260 source/proof normally integrated,
including actual ProfileTrace join in restoration-physical-comparison.json.
UI Up/Down/reverse74.1/75.9/77.9%, idle5.7%; preceding directional01 used
80.6/76.4/80.1%, idle5.6%. Loaded source ranges differ and instrumentation is
included: NO isolated CPU improvement or full reader smoothness claim. Mixed
signs in scroll-demand.json report inherited demand at native scroll changes;
without _restoring/new-sample facts they do NOT refute the original source
counter or prove each change is new user motion. Original raw/proofs preserved.

The no-anchor family boundary remained: ordinary native terminal resize127->70
clamped outside restoration, sampled=True, changed stationary demand to moving.
Unanchored observation is preserved including its runner exit1: a legitimate
idle expiry also violated the earlier strict trim-demand assertion before the
resize assertion. The recorded resize/clamp sample remains original data, not
an asserted complete negative journey. The final source counter isolates those
geometry operations with the existing configurable scroll_idle_seconds=5 and
retains strict trim/resize/new-native-input assertions.

WindowRestoration.geometry is shared independently of a policy instance.
Workspace now enters its scope for EVERY already-registered native window for
both anchored and ordinary reflow. It uses the existing resource registration;
no added window roster, cursor, state flag or timer. Native PageDown afterward
still produces original input samples outside restoration (29 sampled native
changes in the completed control). Trim/resize samples are all geometry, original
demand unchanged, marker/revision preserved, native revision4 remains stable.
Exact whole-window source counter exits0. Per-file measures unchanged except
code_lines; no broad audit/CPU/native/default readiness is inferred.

This last whole-window extension is source-tested; the preceding physical gate
certifies the recorded2f22 product, NOT this subsequently extended product.
One coherent affected installed gate remains before whole254 readiness. All
CPU/warm/focus/TC1/T9/growing-end lifetime requirements remain in original PR254.
Critical258 source freeze7026/6b8 and Sch's replacement bus gate are independent;
this continuation does not alter or delay that reviewed release.

## Current paired dependency integration

Normal main8ea96a37 (whole critical7026 source, Coree191 metadata) and contributor
26398bd363e original-demand-before-await correction normally integrated at
19a6f2f5. One proportional source ABI control used the CURRENT reviewed immutable
runtime-native-applied-cohort-20261001/bin/python: Coree191/Textual6b/SDK0.12.1,
owned254 source imports. Original trim/resize/native PageDown control exits0;
all geometry changes restoring, zero false geometry samples,29 actual native
input samples. No native/ACP/provider/input submission or public root effects.
The prior physical proof boundaries remain unchanged, not retroactively upgraded.
Kepler is sole next physical capturer after whole original-demand async counter
and the actual two-workspace-source helper; Heisenberg retains restoration and
whole254 integration. Parent cutover does not wait on this performance scope.
