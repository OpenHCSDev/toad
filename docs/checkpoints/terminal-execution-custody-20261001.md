# TC1 terminal execution custody

Arendt owns TerminalExecution, ToolState and their ACP/controller/TerminalTool
consumers. Kepler contributes the existing real PTY/ACP journey; Heisenberg owns
viewport/session/transcript paths. Frozen public479/pair source is untouched.

Witness at current8116949e: execution independently stores nullable task/process/
fd/return/startup fields plus released boolean; ToolState reconstructs completion
from two nullable fields, and TerminalTool decodes the return code again.
IMPL-10/IDEN-3: resource acquisition and original process outcome should answer
those questions. Same ANSI model, bounded output and PTY ownership remain.

Trajectory: acquire process/PTY custody as a complete resource, keep task and
startup futures as resources rather than mirrored semantic fields; original
terminal outcome members own ACP status/wait and widget presentation. Controller
address membership owns ACP release, with joined cleanup. Delete replaced
definitions/fields/probes and all tuple/status reconstruction consumers in place.

Acceptance: existing real create/output/normal-exit/signal/release/cancel/startup-
failure and view-detach/reattach journey, without UI/protocol/state mocks or paid/
public inputs. Source and actual installed gates are separate; no live readiness
claim until the affected installed path passes. Headroom guards bound packaging
and fixtures. Report production deletion separately from fixture/evidence lines.

## Working paired source checkpoint

Core480 dependency: 199bbaaa69414c59ed17fb16c556c7a10365f7b2. The original
child_process join algorithm has an identical AST; its declaration and both Core
consumers use the public name `join_retirement`, with no alias or copied loop.
Existing real-process cancellation controls: 3 passed in 7.81s. Toad's locked
dependency now names that exact contribution; Textual6b/SDK12.1/native593 remain.

Against Toad8116949e, production deletes 256 lines and adds 460 across seven
files. Kepler's existing journey extension is fixture code, counted separately.

Deleted semantic copies: execution process/fd/task/startup/return/released fields,
nullable ToolState exit/signal pair, widget return-code decoding, and controller
copied target. One original task/ready resource and AsyncExitStack acquire the PTY
and process together. Acquisition registers retirement before exposing custody;
the public original join protects startup, release, and original child wait
against repeated caller cancellation. ACP address removal happens after cleanup.
Original task failure owns the result; cleanup failures are not blanket-suppressed.

SurfaceBinding owns terminal publication through the original native MessagePump
admission. The obsolete private `_closing` probes are deleted. The granted five-
line Conversation handler delegates to that owner. OperationalTerminalOwner
declares the original controller/binding relation; controller state and resource
membership declare address admission. The same owned relation is checked before
and after mounting. Inactive warm views remain bound. A replaced controller's
address cannot reuse another execution's mounted widget.

Outcome members retain the original rich Core ChildOutcome and own ACP output/
wait plus widget presentation; the OS return-code boundary is decoded once.
All raw output bytes are retained even across partial UTF-8 chunks. The bounded
output reader handles zero and continuation-only suffixes while retaining ANSI.
No native/input/runtime format change, provider call, public restart or replay.

Focused existing session controls: 4 passed in 0.74s. Obsolete fixture construction
now uses the existing AgentDefinition; the official SDK empty write response is
asserted as `{}`. Deleted probes of removed private process fields are replaced
by existing original resource/address refusal and actual receiving acceptance.
Source-only actual PTY normal exit/joined release passed; these are not installed
or live claims. Kepler's single actual installed ACP/PTY continuity gate is still
pending the correctly pinned paired stage. It includes cancel-wait, repeated
cancel-release, startup cancellation/failure, UTF-8 output, kill/signal, detach/
reattach with the same ANSI resource, and closed child/FD/address checks.

Patterns: IMPL-10/IMPL-13, IDEN-3, BOUND-7, TIME-2. A new original process outcome
owns its terminal projection as a family member; unrelated consumers do not gain
another switch. A new bound surface uses the same original MessagePump admission
and ownership relation, with no terminal-specific closing mirror.
