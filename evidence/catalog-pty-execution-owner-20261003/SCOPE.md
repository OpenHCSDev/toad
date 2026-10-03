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
