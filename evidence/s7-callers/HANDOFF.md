# Current core consumer closure

Migrate the six Toad pilots that exercised removed ACP component properties/methods. Use real current Agent RPC clients instead of obsolete SimpleNamespace unbound method fixtures; typed AgentEvent values at the core boundary; declaration-owned queue/session/config owners. Delete the queue pilot source-digest gate. Production Toad already consumes the current external protocol without compatibility shims.

All six passed against the installed combined S7 runtime: goal edit/retry/set, input delivery, input failure, and queue view. Earlier fixture migration failures and final results are in core PR162 evidence/s7-integration. The real configured-provider queued-compaction acceptance also passed there, preserving original/followup order and facts. Pin core to merged PR162. Parent activated the combined runtime on the existing bus with both owners ready and all103identities preserved. CI deferred.
