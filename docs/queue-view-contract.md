# Queue-view identity contract (integration draft)

Status: **not a shipped protocol**. Toad and the sole backend owner are agreeing
an authoritative projection before integrating it. Backend `a380bc0176a1f9a6774494b564b0e44d9eacf007`
still emits text-only queue snapshots. Its PR94 native source cursor is a
separate concern; it does not establish queue membership or acknowledge inputs.

## Evidence and ownership

- Toad base: `b6220b7ab72959f465158699e1dc035238d469dc`.
- Provider-free baseline: `tests/queue_view_event_order_pilot.py`, committed in
  `318ba7c`, with `--expect-baseline-defects`.
- Backend imports for that baseline: `3fc252fd516ecf6660cc83247c00c36d013e10a9`.
- Seven deterministic presentation counterexamples: duplicate start consumes two
  equal-text inputs and echoes twice; stale snapshot resurrects a started row;
  foreign snapshot/start mutates the current view; retired Agent overwrites its
  successor; duplicate restoration appends to the composer twice.
- These are **not proof of the root cause of a live ghost input**. No historic or
  UNKNOWN input is replayed. Input7911 remains UNKNOWN.
- Backend owns queue admission, native start proof, dispositions, owner identity,
  revision allocation, and any remote mutations. Toad projects this information;
  it does not edit backend ledgers or infer model consumption.

## Confirmed requirements

1. Every admitted row has an immutable `inputId`; equal text is not identity.
2. Snapshot and start/disposition events carry session and owner-incarnation
   binding plus monotonic revision. Foreign/retired sources cannot mutate the
   current view, including already queued UI messages.
3. Start proof retires the exact queued row at most once. It does not prove
   completed work or resolve UNKNOWN disposition.
4. Empty snapshot and control ACK prove neither consumption nor completion.
   Removing a queue placeholder never erases an unresolved input record.
5. Reconnect to the same owner retains revision floors and duplicate protection.
   Restart requires authoritative owner rebinding; it does not clear UNKNOWN.
6. Remote edit/remove/clear requires backend exact-ID, revision-checked mutation.
   Until that exists, Toad holds those controls unavailable. It must never
   implement them by clearing everything and resending retained text.
7. Local unsent drafts are distinct from admitted input IDs and remain editable.
8. A trusted new/load-session response establishes binding. Arbitrary queue
   notifications cannot teach the consumer a new owner incarnation.

## Backend proposal adopted for further integration

The backend owner reconciled the earlier field-name proposals: the following
semantics are agreed, still pending implemented schema/fixtures and an exact
freeze:

```text
trusted new/load/owner-socket ready.agentComms.queueBinding = {
  sessionId, ownerThread, ownerCreatedAt, ownerEpoch, admissionGeneration
}
queueState = {
  version: 1, scope, revision, items: [{inputId, text}], restored: [{inputId, text}]
}
inputStarted = {scope, revision, inputId, text}
```

Only trusted new/load/ready results may rebind scope. The same result includes
an initial queueState snapshot at its revision. Queue events cannot establish or
replace scope. Exact starts and public dispositions use the same scope.
Prebind callbacks are bounded-buffered per session; after binding and the initial
snapshot, matching-incarnation snapshots must meet the revision floor. Exact
start proofs use the separate rules below, including delayed older proofs.
Overflow marks projection unavailable, requiring read-only refresh or reconnect,
never automatic input replay.
Revision increments per membership change, not per emitted message: an exact
start and the following queue snapshot share the removal revision. Therefore
an equal-revision start still retires its input once; a per-scope started-ID
tombstone prevents snapshot replay from resurrecting it. Lower-revision snapshots
are ignored. Same-owner reconnect retains revision floor and tombstones; trusted
changed-epoch rebind resets projection bookkeeping, never durable UNKNOWN.
Duplicate restored IDs append to the composer at most once.

Within the same trusted owner incarnation, an exact older-revision start may
arrive after a newer snapshot. If that ID is absent from newer items, accept the
proof/history once without clearing other rows. If the newer snapshot still
contains it, mark the projection contradictory/unavailable and require read-only
refresh, rather than silently retiring it. Thus the snapshot revision floor must
not blanket-reject durable start proof. This never implies work completion.

Tombstone storage must be bounded without evicting IDs and later re-echoing them:
on overflow, fail closed/unavailable until authoritative refresh, or suppress
unrecognized older start IDs. The actual bound and refresh mechanism remain to
be specified in backend fixtures.

Details required in the backend schema/fixture freeze before wire integration:

- Version support and exact scope types/validation/bounds.
- Fixture for initial snapshot/ready ordering and bounded pre-bind notification
  replay, including overflow/unavailable behavior.
- Reconnect replay ordering, deduplication bounds, and disposition scope.

## Acceptance matrix

Run through actual Agent/Conversation queues with disposable state, no provider:

- Queue identical text IDs A/B; start B; only A remains and B echoes once.
- Repeat B start; neither A nor the composer changes.
- Start before a delayed older snapshot; no resurrection.
- Same snapshot on reconnect; no duplicate rows, echoes or restored draft text.
- Wrong session, wrong incarnation, retired Agent and stale revision: no mutation.
- Batched valid updates without per-notification queue drains still project the
  authoritative latest state correctly (no mutable-producer-state shortcut).
- Queue clear hides membership only; unresolved disposition remains UNKNOWN.
- Missing/malformed binding or unsupported version fails closed, without text
  matching or adopting the incoming owner identity.
- Stale menu callbacks and direct queue-replacement calls make zero remote
  clear/send/cancel calls; local draft remains editable.

Independent review of `09bb5d3` is CLEAN only for the last control-hold boundary.
The seven original event-order counterexamples remain unresolved at that commit.
