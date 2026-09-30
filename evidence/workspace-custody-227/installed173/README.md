# Snapshot cancellation custody: PASS

Exact noneditable installed Toad173901b9329af36116158ec492db839af7d872c6,
Core000a31c562b6d048e26e288b24fcd3f1ac64f803 and Textual65053c5a2df12249ef1c4193beeff7023c1f75d7.
The actual Toad app, real unstarted ACP Agent resource, native journal parser,
SnapshotPublication, preparation workers, Window registration and Textual lifecycle
run. No ACP process, provider, original live root or physical capture is started.
Two private deterministic six-row native sources exercise replacement custody.
This is the missing bounded resource gate, not a full native/physical workflow.

Before acceptance: hold the actual completed mount's await. New native history
is attached ProvisionalTranscript with coverage false; original remains Live.
Cancel the real SnapshotPublication task. Its existing finally removes provisional
history and unregisters it; original remains the only registered resource.

Accepted retirement: hold the original history's real Unmount handler. The new
history is Live/accepted; original is ClosingTranscript, denying publication.
Cancel the real publishing waiter. New remains Live. Original stays temporarily
attached/registered/coverage true while its explicitly held teardown runs; this
transient closing cohort is recorded rather than called immediate removal.
Release actual Unmount. Independent Textual teardown completes, original detaches
and unregisters, leaving exactly the accepted new native resource. App exits normally.

Textual650 remove_children calls App._prune synchronously, posting Prune to all
selected resources. call_when_ready admits the independent AwaitRemove finisher;
__await__ shields its completion. Caller cancellation does not cancel those widget
message pumps or the independent completion. No Snapshot production change or
count-based deduplication is needed. Sch215 remains source implementation owner.

Command (one completed60s-bounded run; do not repeat without a concrete risk):

```sh
CUSTODY_EVIDENCE="$PWD/.artifacts/snapshot-custody-installed173" timeout 60 \
/home/ts/wt/toad-canonical-wire-transcript-20260929/.artifacts/installed-source-admission09/bin/python \
tests/snapshot_cancellation_custody_pilot.py
```

Resource semantics IMPL-12/IDEN-3: teardown belongs to existing native owners,
not the publishing waiter's lifetime. One owner; no compatibility alias, release
flag, registry, cache or competing model state. Native source admission vs painted
read acknowledgment stay distinct. Whole227 workspace/performance acceptance
remains open; parent owns installed/default cutover and its entrypoint gate.
