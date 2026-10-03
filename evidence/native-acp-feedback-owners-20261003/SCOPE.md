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

## Shared source claims

Heisenberg granted `agent_surface`, `Conversation.on_agent_fail` and
`agent_turn_over`, and ToolCall header methods. Viewport, body lifecycle,
preparation/renderer and sidebar resource methods are excluded. Existing
permission/PTY and explorer evidence from #356 remains preserved.

## Delivery

Before/after source evidence uses the existing NRA AST parser over production,
tests and the relevant dependency roots. Dynamic receiver ambiguity is reported
separately. After implementation, batch affected sanity and one installed
application publication/header path. No provider inputs, authentication,
public stores, new worktree or environment; CI deferred. No full headless or
physical readiness claim from this scoped checkpoint.
