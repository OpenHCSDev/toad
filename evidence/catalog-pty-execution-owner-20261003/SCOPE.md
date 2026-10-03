# Catalog PTY execution owner

Source reasoning precedes implementation and final validation.

`CommandPane` repeats PTY acquisition, process/input handles, resize, read,
completion, and TERM/KILL retirement already owned by `TerminalExecution`,
`TerminalOperation`, `PtyProcess` and `AttachedChild` (IMPL-13 / IDEN-3).

Reuse those original owners. The mounted pane borrows the original execution
and ANSI state. Preserve sequential bootstrap/prefix output and catalog `/bin/sh`
versus ACP's configured shell. Publish action completion only for its final
command. Cancellation joins the original execution, including cancelled startup
and native worker retirement; no copied process/task/return-code fields.

The complete production family is terminal_execution, ANSI stdin binding,
CommandPane and ActionModal. TerminalTool retains its existing ACP acquisition
contract. Existing catalog and mounted-PTY fixtures consume original custody.
Heisenberg granted these process/projection hooks; CSS/layout/frame work excluded.

Before evidence uses the existing refactor-audit Package loader over all 288
production and 391 test modules, zero omissions. Lexical hits are read semantically;
they do not establish dynamic receiver resolution. ChildOutcome/AttachedChild
contracts were read from the installed Core donor, without modifying it.

Final validation: one affected installed original App/catalog/real-PTY journey,
including success, nonzero exit, sequential bootstrap, input and cancellation.
Receiver owns packaging. No new environment, provider, auth or public mutation.
No latency, physical pixel or full headless completion claim.

## Working source closure

Four production files: 112 added / 197 deleted at this checkpoint (remeasure at
Ready). No classes added. Pane no longer opens PTYs, starts subprocesses, stores
process/master/task/code, decodes output, writes via a delayed thread, or sends
signals. It holds one original execution resource. The original async worker
awaits it; finally joins original custody even during early native teardown.

`Command.for_script` owns catalog shell/environment; `Command.shell_command`
owns launch arguments consumed by the SAME `PtyProcess.acquire` for ACP/catalog.
`TerminalCompletion` derives exit/signal return codes from original ChildOutcome.
`PtyProcess` queries its owned FD for cooked mode. `TerminalOperation` answers
unacquired/running/completed cooked queries without another mode flag.

`TerminalState.bind_stdin` binds the operation that consumes an existing model;
no buffer/provenance is copied. Constructor optional `state` is an ephemeral
resource argument, not stored nullable lifecycle. ActionModal retains its original
main execution while bootstrap borrows that SAME state, then starts main. Only
final command completion publishes the catalog event. Official precompletion
return-code absence remains a derived public query, never a stored status.

All CommandPane creation/execute/private test consumers migrated, including demo
and the older mounted-resume pilot. ACP TerminalController/TerminalTool retain
original operation creation, detachment, outcome and retirement consumers.

Existing catalog pilot extends the SAME journey with real local curl/sh bootstrap
and typed command config, native cooked input, original custody closed/retired.
No provider or installer network call; no alternate application/protocol/model.

ActionModal also replaces `_command/_env/_cwd` with one original `Command`
constructed at the action boundary and consumed by execution/prefix paint.
