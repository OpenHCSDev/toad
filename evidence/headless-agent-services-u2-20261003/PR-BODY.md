# U2 original service checkpoint

Production source: `c1d653991a94686a167ed04b1e6f4a99641cd1e9`. 251 production lines deleted, 247 added across21 files.
Original declarations moved; caller and obsolete forwarding paths deleted together.
Patterns: IMPL-13 (shared read/work behavior), IDEN-5 (removed root/app copies),
TIME-6 (removed delivery intermediary and task facade).

## What changed

The existing attached surface acquires application resources. The operational
controller receives that binding. One original transcript reader owns its lock,
service and delivery; reattachment to the same application resources reuses it.
Each in-flight read retains its original resource, with content and publication
checks after awaits. SDK validation and worker operations use their original
families through native process delivery. There is no second app/root mirror.

## Actual acceptance

The installed original worker accepted typed SDK data and refused invalid data.
The installed Toad/ACP/Pi journey reached a native answer, reconnect/saved paint,
file operations, permission grant, terminal paint and reuse, channel return,
draft/document/undo preservation, and permission detach/reattach/reject. Original
reader lock cancellation and service reuse passed before input. One controlled
localhost request, zero provider errors. This uses Textual Pilot, not st footage.

The continuous journey then FAILED at the existing new-session DB timestamp
encoder. `TypedTable._Field.encode` already returns TimestampText; the local
storage encodes that string as datetime again. Parent/Mendel have the original
trace. This failure was present before350. Final driver-end reader assertions,
new-session title and stop-pending permission checks were not reached.

The earlier run stopped before native input at my incorrect attachment caller;
that caller was fixed and the original failure retained. No input was replayed.
Attempted pytest/optional-renderer checks did not run because those dependencies
were absent. No new environment or native copy was created. No public defaults,
owner, store or user session was changed. Cleanup found no readable processes
carrying the owned attempt IDs; inaccessible system processes are listed, not
silently treated as inspected.

## Scope and next work

This checkpoint is the implemented U2 service/resource closure. Full U2
preferences isolation, U4 frontend views and U5 model extraction remain open.
Detached geometry belongs to the existing TerminalState/TerminalExecution
width/height/resize declaration; do not add another dimensions owner. The current
80x24 detached default is preserved by350. Replaced defaults will be deleted in
U5, together with configurable detached operation consumers.

See RECEIPT.json for exact paths, original negatives, counts and scope; before
and after maps use the existing NRA AST parser with zero omitted source modules.
Dynamic receivers/unrelated lexical names remain explicit ambiguities.

No CI wait; parent review/publication remains separate.
