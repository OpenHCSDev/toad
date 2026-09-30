# Accepted pre-prune cancellation custody

Installed c9aa8302a27f42c261431d36f1b74f103c2180d9 fails both new cases.
Installed b6fa2a725d7f42a2bf0202b2d0eb2374d652c3a4 passes both.
Both use Core2519fb653d3dde780da729d8979b55df68026b95 and
Textual65053c5a2df12249ef1c4193beeff7023c1f75d7, with identical test inputs.

Actual ToadApp, Window registry, native TranscriptHistory, SnapshotPublication,
CheckpointPublication, LiveOutput, ResponseStream, source reader, rendering workers
and Textual teardown execute. Two private six-row native journals are declared in
the real private registry. The real ACP Agent resource is never started. There is
no ACP process, provider, original live root, owner restart, input replay or capture.

## Concrete cancellation boundary

Hold the existing LiveOutput.lock. Observe the real retire_presentations admission,
then cancel the accepted publishing task before native Prune is admitted. The
observation wrapper calls the original retirement; it neither replaces admission
nor decides coverage. Release the lock and await the actual cancellation result.

Snapshot baseline retains two attached, registered, coverage-bearing histories.
Candidate keeps its publishing task pending while the lock is held; after release,
old native history detaches and unregisters, accepted replacement remains sole.

Checkpoint uses the actual settled source capture and private registered source
reader to cover an original live ResponseStream widget. Baseline leaves the widget
and stream association attached after cancellation. Candidate removes both before
propagating CancelledError. Its native history survives. Checkpoint advances or
replaces history independently; this case does not claim the old history was a
retirement candidate. All four applications exit normally; baseline exit1 comes
from the preserved post-receipt assertion, candidate exit0 from passing assertions.

## Ownership and limits

Schrodinger owns the production retirement helper and both publication consumers
in PR229. PR227 extends the existing custody pilot and retains failing and passing
receipts only. IMPL-12: one retirement helper owns the shared completion contract.
IDEN-3: existing native resources and stream associations report their custody;
no registry, coverage mirror, cancellation flag or replacement renderer is added.
A new retiring presentation inherits this helper; no per-kind consumer edits.

Old173 proof covered cancellation after independent native Prune had been created.
It cannot certify the new await before Prune. The original mount/prune pilot now
releases held Unmount before awaiting cancellation, honoring the candidate's joined
retirement completion while retaining both preacceptance and postacceptance checks.

This closes the specific merge-held cancellation risk. Existing39chunk native
normal-journey evidence is separate and was not repeated. Full227 warm resources,
keyboard, growing-end, video/CPU and whole T9 acceptance remain open. Nothing here
claims global activation or complete physical workspace acceptance.

Exact commands and package pins are retained beside each red/green receipt.
Each run is bounded by45seconds; fixtures are deleted after app exit, receipts kept.

The adjusted original mount/prune case also passed on exact installed b6,
with provisional cancellation preserving the original and accepted cancellation
completing old Unmount before final cancellation propagation. This small resource
check verifies the changed completion contract; no native provider journey reran.
