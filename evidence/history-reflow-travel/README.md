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
