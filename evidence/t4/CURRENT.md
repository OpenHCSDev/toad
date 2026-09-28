# T4 current implementation checkpoint

Base: merged Toad125/main 67ddc9e6. Own persistent tree; no live installation changes.

Nominal owners: ConversationTurn/TurnOwner, ContentNavigation/BlockCursor, AgentProcess/ProcessControl, AgentPresentation, QuestionPresentation/QuestionMount. Removed string turn authority, BlockProtocol and duplicate cursor methods, ACP Agent-owned subprocess/task machinery, and Question deferred container queries. Actual retained callers migrated; App/MainScreen/workspace lifetime ownership untouched.

PR122 final 94dba8097f2776e90a01547ed63ae1e885837f6a: carried tests/midturn_compaction_pilot.py and final acceptance/recovery receipts directly. Production formatting/comment deltas intentionally omitted; integration base already contains T2 production semantics. Updated mounted midturn expectation passes against installed wheel.

Evidence: installed mixed-block navigation + new block/turn case (2 tests), typed lifecycle/compaction, goal separator, deletion guard pass. Actual native MCP disconnect now passes (1 selected case); event-loop-closed warning remains in receipt. OS process-group retirement exits successfully. Full installed native pilot attaches but times out waiting for first loopback provider request; this is unresolved and no full-native readiness claim is made. See native-turn-process-fixed.txt. NRA package/core-context audit completed; direct bounded edits, no codemod proof claim.

Next: diagnose native turn timeout, final installed native rerun, shared per-class ratchet, final review and merge handoff. Textual layout recursion is separately reported baseline behavior outside this scope. CI deferred.
