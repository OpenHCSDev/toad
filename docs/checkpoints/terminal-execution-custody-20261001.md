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

Initial Core480 dependency: 199bbaaa69414c59ed17fb16c556c7a10365f7b2. The original
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

## Original child-owner closure after structural review

Final paired Core480 dependency: f8ae4f5217561b6b8a2def4cafc2dfda583fcdfe.
Against8116949e current production deletes 265 lines and adds 463 across nine
files. Kepler's single existing helper adds 203/deletes19 fixture lines.

The initial274d01 PtyProcess could skip a surviving group after its leader exited.
Parent's original installed254 control did NOT reproduce a leak; this finding
is scoped to the new274 implementation, not claimed as a live254 failure.

PtyProcess now requires the original AttachedChild and master file. Its copied
process field is deleted, along with Toad's manual subprocess launch, bare PID/
killpg, OS return-code decode and STOP_GRACE retirement loop. AttachedChild's
original exec gate owns identity before command execution. TerminalChildStdio
provides the original slave file; all native streaming defaults remain unchanged.
kill delegates to original child.force (ACP SIGKILL preserved), retirement uses
original child.stop including surviving members of an exited leader, and the
terminal projection consumes the original rich child.wait result. No subprocess
subclass or alternate stop algorithm is introduced in Toad.

The same cancelled acquisition joins its protected spawn, whose complete child/
PTY resource has registered its original cleanup in AsyncExitStack. No lost
nullable handle is reconstructed at exit. The existing original Core group-stop
and public join own cancellation and settlement, including repeated ACP release
cancellation. No task deadline is introduced in Toad.

All22 existing Core child-process/guard controls passed in25.68s. Actual SOURCE
PTY control observed one surviving original child after leader exit and retired
the entire group/master in2.075s. Source controls are not installed/live claims.
Kepler65288a29 is normally merged; it migrates every original-custody consumer and
adds that leader-exited descendant control to the same installed journey. The
single correctly pinned paired receiving stage/gate is still pending. Parent
sole public executor; frozen479/pair remains untouched.

## Paired launch consumer closure

Parent caught the remaining old IO keywords at maintenance_ingress169 before
staging. The earlier Core-only caller-default census omitted this receiving
repo. Corrected full Core/Toad source, tests and tools census covers direct
AttachedChild.start plus BoundedRun.session/admitted_spawn forwarding.

admitted_spawn now consumes and forwards the same original ChildStdio member;
its scalar input_enabled/limit arguments are deleted. AgentProcess's sole
override constructs StreamingChildStdio with the unchanged10MiB ACP stream
budget. The only AgentProcess changes are that import and the launch argument.
No admission/retirement/phase/route behavior was relaxed or duplicated. No
compatibility kwargs, alias or fallback retains the removed signature.

Exact affected SOURCE control: actual admitted_spawn shell/stream/retirement with
StreamingChildStdio(limit=10MiB) passed through original route/maintenance custody.
The installed receiving journey still must launch ACP through this same seam;
no installed or live claim is inferred from the source control. Current original
session controls also pass4/4 in0.76s after the AttachedChild migration.
