# Canonical roster invalidation after a native fork

Owner: Einstein. Integration consumer: Sch, PR228. Source base: fda1b5d2dda13a55a6e3ae400af03a6e76e70ec1.

## Demonstrated failure

PR228 installed candidate05, Toad3f3e / Core095 / Text650 / nativee36,
registers `immediate-fork` with `fork-added`, but the visible current roster
retains only beta and the previous channels after eight seconds. This occurs
before opening the child. Its task is empty and its real worker is held before
the RPC socket opens. No uncertain input is replayed.

Raw proof is protected at
`/home/ts/wt/toad-fork-task-editor-20260930/.artifacts/full-fork-candidate05/fork-roster-state.json`
and the adjacent SVG and native logs. The frame is Presented, navigation is
ready, the sidebar is attached and enabled, and neither observer nor projection
locks are held. These facts locate the failure at publication, without yet
identifying its cause.

## Scope and ownership

Trace the existing CoordinationAccess revision observer through its publication,
SidebarObservation source read and the screen callback/frame lifecycle. Fix the
declared source invalidation boundary and every affected consumer in place.
Do not add another timer, roster/status store, forced frame, compatibility reader
or source cache. Keep PR228 dialog implementation and PR232 response publication
with Sch. Current C3 cohort only; partial FIRSTUI and installed defaults are not
changed here. Patterns: TIME-3/TIME-9, BOUND-2, and declaration ownership from
the current NRA/refactor-audit skills.

## Acceptance pending

Extend the existing installed native fork journey with read-only failure probes.
Verify canonical registration reaches the visible roster, then actual child
opening before its first native reply, edited inherited tags and the reply.
Use a fresh private fixture with the original attempt dispositions preserved.
Retain failed receipts and publish exact source pins, production deletion counts,
cleanup and actual installed evidence. No readiness claim until this gate passes.

## Cause and complete owner closure

The installed probe05 records the swallowed exception:
`AttributeError: 'TranscriptHistory' object has no attribute '_loading'`.
`App.mark_visible_thread_read` accessed that deleted private field before
`SidebarObservation.read` could obtain its current source snapshot. The app's
revision equaled the canonical revision, the canonical snapshot contained the
child and channel, and the sidebar retained its old projection. This was not
missing registration or a dormant timer.

The app now asks the existing source-preparation owner `blocks_visible_read`.
That derived query owns attachment, remaining tail and the existing typed
source/filter checkpoint admission. No state, loading flag, status copy, codec,
timer or compatibility alias is added. All references to the obsolete history
field are gone. The other `_loading` references belong to Conversation's actual
Loading widget and are not aliases for history state.

The same probe found deferred source work still queued after a modal restored
a Presented frame. Written and restored frames now use the single existing
FramePresentation present effect, releasing the same owned callback queue.
Heisenberg confirmed this does not overlap his parked-source/read scope changes.

Own production deletion: **4 lines** across app.py and frame_presentation.py.
The normally integrated PR228 dialog additionally deletes **7 production lines**.
The new admission query remains in its existing source lifetime owner. An
intermediate query on the large widget failed GodClassExcess +5; the rejected
checkpoint and corrected zero-positive-delta ratchet are preserved. No waiver
or new mixin was introduced.

## Installed continuous acceptance: PASS08

Tested source `253eeb101d9f6d28c8a3e0b608e509b6842b2ed5` normally integrates
current main PR230/232 and the PR228 dialog checkpoint. The 68-package installed
candidate uses Core095, Text650, ACP SDK0.12.1 and standalone nativee36; every
installed Toad source file matches the published source. Exact pins are in
`evidence/coordination-roster-invalidation-20260930/ready-receipt.json`.

One continuous actual installed native/ACP/Toad Pilot journey passes exit0:

1. Parent saved answer and native fork dialog, with inherited `team` tag.
2. Empty task; remove `team`, add `fork-added`; parent declaration unchanged.
3. Canonical child registration publishes the new channel and participant row.
4. Actual disclosure/row clicks open the child before its RPC socket exists.
5. The same worker remains pending beyond the former five-second expiry,
   resumes and paints inherited native history, with one logical tab.
6. Actual Enter sends the first new child input once. After its accepted source
   cursor settles, there is one mounted AgentResponse and one occurrence in the
   rendered compositor viewport. The canonical user input also occurs once.

Two controlled loopback model requests; zero external provider calls, public
inputs, owner restarts, default changes or replays. Fixture owners are no longer
alive and no process remains on its private root. Both input records are Started.
The UI driver is the actual installed Textual Pilot, headless; this is not a
physical st recording, default-entrypoint activation or performance claim.

Failed06/07 whole-journey proofs remain failed and preserved.06 exposed the old
test's logical SessionView versus WorkspaceScreen comparison;07 reached the
correct cold child and inherited history, then its diagnostic print accessed a
removed SessionDetails.state field. The existing journey now waits for the exact
logical child and reads no obsolete session-state mirror. Probe02's invalid
monitoring event set, probe03's pre-exec environment race and probe04's syntax
failure are retained as fixture failures, not product evidence.

PR233 is ready for the parent to merge as the coherent PR228/232 workflow
checkpoint. C3 activation remains parent/PR442-owned; this fix is not live.
