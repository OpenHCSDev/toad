## Cancel the native observer when its pipe peer disappears

Independent small follow-up to109, based on currentmain60a87e0 including112. OwnerCopernicus. Production scope: only directory_watcher.py,6added/3deleted lines; no dependency on107 or the nominal refactor.

A real pending-unread pilot exposed BrokenPipeError/ConnectionResetError when the parent closes its IPC endpoint while native notifications remain queued. EOF-only handling missed socket RESET; the dispatch thread could print an exception before observer termination. The failing test demonstrates stderr errors, not a proven persistent child leak.

The child now applies the existing owner-loss cancellation behavior to ConnectionError on both receive and send: exit the observer process, releasing native handles. Parent event reception also recognizes disconnected-child errors and runs its existing join/reap finally block. This does not swallow arbitrary filesystem/observer failures, redirect stderr, or leave a dispatcher running after ownership ends. Existing serialized send lock stays in place.

Actual tests:512filesystem events through the spawned watchdog observer, close the real pipe with unread events, require childexit0 and empty capturedstderr. Current-main before patch fails; installed candidate wheel passes. Existing200-event overlap/readiness test confirms independent dispatch threads, no concurrent writer, later event delivery, reaping andexit0. Full installed copied archival UI: #comms8, agent-comms-ux2, pr95-selected-pi-summary-owner0; messages0; watcher and child joined; interpreter exit0 without tracebacks. Core249wheel and Textual16ede, no paid calls/live edits. Build, scoped Ruff and diff-check pass. Exact evidence in this directory.

Runtime cancellation only; no durable stores, history migration, schema reset or live activation. Parent owns merge/pin. Existing old-runtime/schema2 versus schema3 coexistence belongs Cicero's core activation fix, not this watcher change.
