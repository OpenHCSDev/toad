# Busy coordination reads in transcript publication

Arendt owns the Toad publication consumer paired with Mendel's Core PR537.
Heisenberg retains viewport and workspace ownership in PR331.

The original330 crash rethrows an earlier SQLite error while joining a
transcript worker at shutdown. Core now distinguishes unavailable committed
reads from missing receipts, stale revisions and corrupt storage.

The existing TranscriptPublication family must retain mounted history and
its original source refresh when that typed unavailable outcome occurs.
Capture, source validation, page preparation and handling reads all use this
same publication boundary. No independent readiness state, empty receipt
substitute, broad worker exception suppression or SQL timeout change.

Source ownership and caller migration precede validation. The parent owns the
single affected installed busy-read journey and public publication. This draft
does not claim installed acceptance and makes no provider or public input.

## Source closure

- `TranscriptPublication` owns typed unavailability for capture, page reads,
  source-current checks and original handling reads. Its completion result
  propagates through every publication member, including nested handling.
- `SourcePublicationRequests` retains the same operation in its existing
  one-slot queue, without replacing newer work. A busy exit stops consumption.
  The existing coordination observer resumes it and owns the cadence:
  `WireRevision.expiry_tick` still changes when database bytes do not.
- `WorkingTranscript` retains a source-snapshotted read callback at the same
  observer for scroll and End. The same suspended operation keeps its pending
  destination until that observation; it does not settle into a new per-frame
  edge read. Retirement or source replacement revokes it.
- `ObservedThreadActivity` retains rendered status and its original pending
  read. Its unavailable event cannot publish that retained status as a fresh
  owner observation in Conversation.
- Speculative page preparation ends on unavailable reads without inserting a
  false failed-page identity into its bounded blocked-page resource.

No new queue, timer, readiness authority or SQLite error classifier is added.
Core PR537 owns numeric busy-code decoding and connection closure. Missing,
corrupt and stale reads retain their original distinct meanings.

## Checkpoint strength

The six changed consumer owners parse before/after with no parse failures.
Existing publication guards completed before the original declaration case
stopped on a missing fixture import path. That failure remains recorded.
Only that remaining case was rerun with the existing tests directory supplied;
it passed source/generation fencing, mounted paint and retirement.

Those controls used this Toad source and the frozen Core f74fd7ed source with
the existing Python3.14 package dependencies. They are source sanity, not an
installed busy-read qualification. The matched lock now selects Core cd150be0;
`uv lock --check` passes. No environment, native package or public route changed.

The parent-owned paired installed journey still must demonstrate actual SQLite
contention followed by release and publication, without user refresh or input.
