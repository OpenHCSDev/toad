# Native ACP feedback ownership

U2/U4 continuation after merged #356. Source reasoning first, coherent owner
and caller migration next, proportionate installed application validation last.

## Existing owners and concrete gap

`AgentFail`, `HelpAgentFail`, `LogAgentFail`, `StopReason` and `ToolCallStatus`
already own the original failure/reason/status data. Their methods currently
construct Textual content or widgets, so importing the operational ACP families
does not establish a toolkit independent behavioral boundary.

The existing `AttachedSurfaceBinding` owns attached native projection and
already composes `MroDispatch`. The existing `ToolCall` owns its mounted header.
Reuse those owners; do not add a frontend registry, renderer wrapper, status
copy or another event. Core families retain their original nominal identities,
notes, help text and operational effects. Native constructors leave those
families in the same change that migrates their complete callers.

The complete production receiving sites are `Conversation.on_agent_fail`,
`agent_turn_over`, `on_acp_tool_call_update`, and
`ToolCall.tool_call_header_content`. Failure rendering borrows the publishing
agent's surface, not a newly selected agent after an await. The native surface
checks its original target identity before presentation. Tool header handlers
borrow only the current Content assembly list; no status or result is retained.
The original status owner still decides activity and output boundaries, taking
those original owners instead of a widget. Stop notes stay on the original
reason family and are constructed at the single existing native receiving site.

Removing AgentFail's abstract *native* method means the existing data-bearing
base can represent a plain failure as well. Its original generic receiving
handler still renders message/details; optional help/log presentation derives
from the existing richer subclasses. No production caller constructs the base,
and no existing failure producer, stored field or wire spelling changes.

`status` now has no native import; `core.events` has no widget import. Other
indirect core debts such as PlanItem and OutputStream's native methods remain
outside this checkpoint, so complete transitive UI independence is not claimed.

## Shared source claims

Heisenberg granted `agent_surface`, `Conversation.on_agent_fail` and
`agent_turn_over`, and ToolCall header methods. Viewport, body lifecycle,
preparation/renderer and sidebar resource methods are excluded. Existing
permission/PTY and explorer evidence from #356 remains preserved.

## Delivery

Before/after source evidence uses the existing NRA AST parser over production,
tests and the relevant dependency roots. Dynamic receiver ambiguity is reported
separately. After implementation, batch affected sanity and one installed
application publication/header path. The final affected check sends no prompt/provider request or authentication
input and changes no public store, worktree or environment; CI deferred. No full headless or
physical readiness claim from this scoped checkpoint.

## Native lifetime and preserved negative checks

The registered SDK update enters SessionNotificationOwner, validates through
ApplicationValidationOwner, updates SessionToolCalls and publishes the original
CoreEvent. Conversation's handler applies status activity, then awaits post;
CategorizedMount admits the nominal ToolCall and Textual owns mount. Its
on_mount awaits the original ToolOutput.sync and its on_unmount retires that
output resource. No active-turn condition exists in post. ManagedTurnBinding
ignores locally invented activity: only the original backend turn publication
can make a managed view busy.

CapturedClaim captures only settled output. Accepted saved-source publication
can replace precisely that captured projection. A notification injected into an
idle fixture does not prove a real native tool or durable saved result; requiring
its indefinite DOM retention was the wrong oracle. Final instrumentation calls
the original ToolCall.on_mount unchanged and records the native header there.
It does not invent a turn, suppress retirement, or grant source coverage.

Failure delivery belongs to its original subscription/publisher. After posting
the main error note, Conversation reads that publisher's current surface. A
surface retired during the await has been replaced with DetachedSurfaceBinding
(or a different target); its existing capability acquires no old-view native
work. The attached hook checks original target ownership, then post relies on
the existing attached contents and native message-pump closing contract. There
is no independently stored pending failure or copied selected-agent state.

Checks02/03 admitted an idle SDK tool but timed out on DOM retention;03 records
registered RPC acknowledgement, original call ledger and active exact surface.
Check04 reserved one private prompt, reached preparation, made ZERO provider
requests and timed out; that original reservation and raw failure remain, with
canonical private-process cleanup. No attempt is retried or reclassified.
Check05 sends no prompt and times out BEFORE feedback acceptance, waiting for
ACP attachment on old Core85. Its worker was observed waiting on a kernel
store lock with both BUS and WIRE descriptors; a later dump after runner exit
was idle. This is not an exact563 deadlock proof and no causal claim is made.

The reused302 holder now normally installs merged Core563 through frozen
requirements. That merged change closes the certified read descriptor inside
the joined worker before Future delivery and moves publication off the loop.
It changes the original startup/publication resource used by this check;
Toad's six-file projection source, Textual and native package remain unchanged.
The next affected App/header check sends ZERO provider inputs. Public563
release is independent of359.
