# ACP accepted-child retirement (local cooperative scope)

Toad launches its ACP shell in a new process session. `Agent` records its leader
PID, creation time, and PGID immediately after accepted spawn. `Agent.stop()`
returns `GroupRetirement` only after a bounded TERM/KILL sequence and a fresh
non-zombie process-group scan. If identity enrollment, signaling, observation,
or the deadline fails, it raises `GroupRetirementUnresolved` and retains the
original PGID and identity. Cancellation also retains them. An unsettled
accepted spawn is a separate admission state: stop waits for the exact spawn
result before cancelling the agent task. If admission does not settle by its
bounded deadline, stop raises unresolved without cancelling the pending spawn;
a subsequently accepted child sees the stop request and retires before ACP
requests. `McpClientStopped`
may be emitted as soon as a stop is requested to invalidate the live MCP UI
projection, **before** any OS process or connection has stopped. It is never a
retirement receipt. Connection EOF likewise proves only stream closure, not
process-group retirement.

A migration controller must pause new Toad ingress, inventory **every** accepted
ACP child, stop each, and call `verify_retirement()` on the pinned original
identity immediately before its route transition while the pause remains held.
The route publisher/withdrawal still owns its EX lock. This slice neither
implements that controller pause nor proves that descendants which deliberately
escape the process group have stopped; escaped descendants require a separate
inventory or the transition remains blocked. It does not stop any live owner,
change the production route, restart a child, replay UNKNOWN, or clear sessions.

The local single-UID cooperative trust boundary in `plans/trust-boundary.md`
applies; same-UID filesystem/process tampering is not the threat model. The
in-scope hazard is a normal child or descendant surviving a bounded stop while
Toad reports success or a route is published.
