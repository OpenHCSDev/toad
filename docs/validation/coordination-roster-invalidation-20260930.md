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
