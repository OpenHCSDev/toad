# Saved-history handling consumer

This narrow change adopts the exact HistoricalSessions bytes qualified in
F4 production11e138357982af03f4f20cf18d571d3665958a38. Current main34633149
already owns MessageHandlingRequested, CoreEventReceiver and handles through
the existing wire widget and Conversation consumer. HistoricalSessions alone
references the removed WireMessageHandling.Requested class at import time.

HistoricalSessions now inherits the original CoreEventReceiver and registers
its existing request_message_handling with handles(MessageHandlingRequested).
It receives CoreEventMessage; original stop, source selection, notification read
and selection-generation behavior remain unchanged. No new event, publication
owner, guard or restored retired declaration. Production deletes3/adds6 lines
in one existing file, byte-exact to qualified11e. No dependency/pin change.

Original Package AST on the qualified F4 source parsed288 production modules,
zero omissions, before/after; the stale event reference is removed. That evidence
is retained in425 f4-handling-consumer-before/after.json. AST is source evidence,
not delivery proof. The existing installed import/handler receipt proves
HistoricalSessions constructs and selects its original handling method through
MRO dispatch. Original actual plain st/Xvfb LinuxDriver saved App06 passes16.512s
and closes fully; native child is retired and original saved source/input/wire
proofs are unchanged. Compact original receipts are copied here unchanged.

Those receipts qualify the exact repaired file within the paired F4 installed
cohort, not a separately installed main-only cohort or archived notification
delivery. Typed context labels belong to F4 and are not introduced by this PR.
No run, provider, input, new holder, environment, worktree or native artifact
was created for this extraction. Original failed App01 stays failed in425.
