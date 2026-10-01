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
