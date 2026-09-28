## Pending unread feedback on current main

Small standalone extraction of the same implementation owned in PR107, based on cc2d35. Pins agent-comms PR249 head492e26de354df6fe020ca69b55fdcd92fb06778e. No dependency on Comms229, S12, or the broader Goal/queue/ProcessIdentity changes in107.

Existing session_tracker presentation owner now distinguishes ExactUnread from IndexingUnread. All thread rows (native and virtual), session tabs and direct thread projections consume that contract. Pending transcript indexing displays “Indexing…” with an explanatory detail instead of falling through to exact zero. DM/channel wire counts remain exact. Deleted integer badge consumers; no compatibility decoder or duplicate registry.

Only presentation/runtime state changes; no durable store, migration or live installation. Parent owns pairing with core249 and resetting its disposable schema3 transcript index at activation. Native history and durable read positions are untouched.

## Installed acceptance

Core249492e26d wheel + this Toad wheel + Textual16ede installed in an isolated persistent target. Real8192-record Pi transcript: native rows/tabs and virtual rows/tabs each display Indexing…, then exact8192, then read-zero; both process exits0. These use real core SQLite/indexing and actual mounted UI, with no mocked unread state or provider calls.

Actual copied archive: #comms8entries, agent-comms-ux2, pr95-selected-pi-summary-owner0; messages sent0; watcher and child joined, interpreter completion marker, exit0. Uses Cicero's accepted current-main copy/rebinding probe; original files unchanged. Prepared-bar worker/caller check, thread unread/start and channel/DM navigation pilots all pass with process exits0. Scoped Ruff, build and diff-check pass. One remaining old test assertion was migrated from integer truthiness to ExactUnread equality after the focused test caught it.

Limits recorded honestly: the native incremental test's process exits0 but its watcher child printed BrokenPipeError/ConnectionResetError during teardown. The archival acceptance exits cleanly without that error. Copernicus owns this separate watcher cancellation follow-up;112 changes no watcher code. The initial typed test exhausted25seconds at256records per UI refresh; the same8192records pass within45seconds per mode, without bypassing the UI cadence.

No live activation performed. Core249 is merged; parent can merge/pin this independent Toad fix and reset only the derived schema3 index. Broader107 work stays separate.

Source:78 added/28deleted lines across seven existing files. Tests:99added/9deleted, including the new86-line actual incremental UI pilot.
