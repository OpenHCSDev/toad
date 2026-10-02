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
single affected installed busy-read journey and public publication. The actual
physical first-End busy/release scope is qualified below. No provider or public
input was made for it.

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

## Physical busy/release acceptance

Heisenberg's completed copy02 used actual plain-st, installed Toad/ACP and a
private copied Native6 saved source. Core cd150be0 and Toad56580c8f were installed
byte-equal to their reviewed source; Text3dd989 and native00c2 were unchanged.
The private SQLite exclusion lasted8.447s. The actual st exited0, all owned
capture processes retired, and the original source hash remained unchanged.

The original review reported failure because it required a queued latest
destination for the first End. Source and the original trusted snapshots show
that first End on `LiveTranscript` reserves `WorkingTranscript` and schedules
`_jump_latest`; its pending slot remains `IdleViewportRequest`. Only another
End while that operation is working creates `LatestViewportRequest`.

Those same original snapshots show the reader Live/gen0 with a newer tail,
busy End Working/gen5 with an idle pending slot and newer tail, then automatic
release Live/gen8 with no newer tail. The same native frontier, selected session
and window were retained. End arrived at the bottom without refresh or input.
This is held native work, not a cache bypass or a lost request.

The failed recorder receipt and review remain unchanged. A separate corrected
semantic assessment records their hashes and the source relation in
`evidence/coordination-read-publication-20261002/physical-copy02-semantic-closure.json`.
No UI run, provider call or production edit was repeated to obtain this result.

This qualifies the physical first-End busy/release path. It does not qualify a
second End, physical source revocation, full handling refresh or performance.
Operation object identity was not exported and is not invented. The pair is
ready for merged receiving; public activation and its fresh channel probe remain
parent-owned.
