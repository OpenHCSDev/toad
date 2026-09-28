## Pending unread feedback on current main

Small standalone extraction of the same implementation owned in PR107, based on cc2d35. Pins agent-comms PR249 head492e26de354df6fe020ca69b55fdcd92fb06778e. No dependency on Comms229, S12, or the broader Goal/queue/ProcessIdentity changes in107.

Existing session_tracker presentation owner now distinguishes ExactUnread from IndexingUnread. All thread rows (native and virtual), session tabs and direct thread projections consume that contract. Pending transcript indexing displays “Indexing…” with an explanatory detail instead of falling through to exact zero. DM/channel wire counts remain exact. Deleted integer badge consumers; no compatibility decoder or duplicate registry.

Only presentation/runtime state changes; no durable store, migration or live installation. Parent owns pairing with core249 and resetting its disposable schema3 transcript index at activation. Native history and durable read positions are untouched.

Validation in progress against actual installed candidate wheels: an8192-record real Pi transcript must transition pending→exact8192→read zero in both native and virtual rosters and tabs; copied archival #comms plus two DM views must render and exit normally, without sending messages. Build, scoped Ruff and diff-check pass. Initial combined typed-candidate pilot exhausted25seconds because the UI refresh cadence allows256 records per second; workload retained, each display mode now tested independently with45second inner/60second process bounds. Acceptance results follow before ready.
