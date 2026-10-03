## What changed

The actual helper493 operation finished4.989s before the saved UI capture. The original captured sidebar has the same turn finished/idle while chat shows Waiting for input start. The ACP log contains the active notification but no terminal notification before capture. This proves the captured discrepancy, not a permanent deadlock.

Removed `OrderedManagedTurn`, `accepts_snapshot`, `turn_class`, the nullable turn-policy argument and `Agent._receive_comms_metadata`. They made backend busy mean that this frontend owned an ordered response, then refused canonical settlement.

The existing `ManagedTurnBinding` borrows original `TurnState`; all turn views derive from it. The existing `OwnerSnapshotConsumer` takes original goal metadata and `ThreadPresentation.read_identity.thread.turn_state`. Session/process, root/incarnation, publication sequence and matching finished-turn fences remain.

The original controller's local operation resource now has one lifetime across text, blocks, send-now and manual compaction. Its last release schedules a fresh same-owner read through the existing `AgentProcess` custody, so a read rejected during local input cannot remain stranded. No timer, pending flag, snapshot cache, extra status field, RPC poll or per-widget clear was added. A failed read establishes no settlement or disposition.

## Whole family and deletions

Five production files:93 additions/57 deletions against currentmain363. Stream/new/load/goal/thread reads use the existing typed consumer. All four prompt entrypoints use the same original local custody. `TurnActivity`, Prompt, SessionDetails, throbber, response retirement and transcript settlement already consume the original binding; no independent view status is introduced.

Queue/start receipts remain with `QueueAttachment` and the producer. Human `InputDocument` delivery and managed `NativeRuntimeInput` are distinct originals. Cursor availability remains with the original scope/envelope/proof; a reply does not create a cursor proof. Mendel confirmed no current-admission cursor row, and absence of a human row for managed493 is legitimate. No UNKNOWN/input493 replay, new native enrollment or public owner recovery.

Existing NRA/refactor-audit Package AST evidence covers286 production Toad modules,390 test modules and311 Core dependency modules without parse omissions. Before/after outputs are committed. Lexical evidence does not claim dynamic resolution; the selected family was read semantically. Patterns IDEN-1, IMPL-12, TIME-6.

## Validation and current readiness

Source-first ownership implementation is published. Final source batch:four checks passed. The obsolete three-line ACP facade assertion was deleted and its remaining guard passed. Its original failure is preserved in `source-sanity.json`. This is not installed acceptance.

Installed01 failed before attachment because the old helper returned a raw catalog dict; the fixture now decodes through existing AgentDefinition. Installed02 attached and caught my missing ClientSessionRequest import at the changed read boundary. The import is fixed and all five changed files were reviewed for required bindings/signatures together; both negatives are preserved. The same private wheel is being refreshed before one corrected affected check.

The sole affected installed App/ACP check uses the actual configured retained helper source, its recorded original active notification and a genuine canonical read. It also checks a read refused during held local operation custody is automatically reconciled on release. No input/provider call or replay is required. Installed result is pending; original source/capture and cursor warning are protected. CI deferred. No full performance/default-live claim.
