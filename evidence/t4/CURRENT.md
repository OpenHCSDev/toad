# T4 current implementation checkpoint

Base: merged Toad125/main 67ddc9e6. Own persistent tree; no live installation changes.

Nominal owners: ConversationTurn/TurnOwner, ContentNavigation/BlockCursor, AgentProcess/ProcessControl, AgentPresentation, QuestionPresentation/QuestionMount. Removed string turn authority, BlockProtocol and duplicate cursor methods, ACP Agent-owned subprocess/task machinery, and Question deferred container queries. Actual retained callers migrated; App/MainScreen/workspace lifetime ownership untouched.

PR122 final 94dba8097f2776e90a01547ed63ae1e885837f6a: carried tests/midturn_compaction_pilot.py and final acceptance/recovery receipts directly. Production formatting/comment deltas intentionally omitted; integration base already contains T2 production semantics. Updated mounted midturn expectation passes against installed wheel.

Evidence on installed noneditable Toad wheel:

- Full native Pi pilot passes prompt execution, queue projection/consumption, native input mapping, cold reattachment, DM replies, channel active/idle status, IGNORE notification feedback, stopped-owner reopening, and idle observation. Loopback model only; no paid calls. Exit 0, native-turn-final.txt.
- Actual MCP disconnect case passes against final wheel: 1 passed/3 deselected, native-disconnect-final.txt. A closed-event-loop process watcher warning remains; the mounted Question callback failure is gone. This is not a claim that the entire MCP matrix ran.
- Installed mixed block navigation/new block/new turn case: 2 passed. Typed lifecycle/compaction and goal-separator pilots pass. Updated PR122 midturn pilot passes. Permanent deletion guard passes.
- Per-class debt ratchet: zero positive deltas. Conversation -116, ACP Agent -169, AgentResponse -42; BlockProtocol deleted. ratchet-summary.txt.
- Initial native attachment timeout was isolated-environment missing pi-comms-native executable. Installed core console entry point restored in own .venv; live launcher untouched. Full native rerun then discovered channel structural widgets excluded by block admission. HistoryLoading/ChannelActivityTray now declare nominal block ownership, and the full path passes.
- NRA package/core-context audit completed; direct bounded edits, no codemod proof claim. No App/MainScreen/workspace lifetime edits. CI deferred.

PR122 closed after exact three-path comparison against 94dba80 and installed test pass. No unresolved blocker for this T4 slice. Parent owns review, integration order, and live installation. Existing Textual layout recursion is separately reported baseline behavior outside this scope. Source changes implement owners in place, without compatibility aliases or restored retired mechanisms.
