# Viewport reconciliation custody

Successor from actual main465 `cac7268a733f62f6db57580fd63b64abd52be359`.
Heisenberg released this exact source seam after the original TC1 read; he
retains whole TC1/workflow,460 and the separate inactive-presentation budget
family. No active control, installed package or frozen artifact was changed.

## Existing owner does the work

DocumentViewport now retains only its original native Worker as reconciliation
custody. `request` coalesces pending demand and starts work when that handle is
absent. `_reconcile` clears only its own handle, using the original
`get_current_worker` identity. `suspend_source` already revokes the handle before
cancelling and awaiting it; `resume_source` admits its normal frame callback;
`close` joins suspension before releasing warm resources. Their original
pending-demand and source-suspension decisions remain unchanged.

Deleted all three `_running` stores and its admission read. Migrated all16 original
control reads in11 modules to the same original handle; retained their existing
body readiness, pending demand, source admission and actual paint assertions.
No production consumer outside DocumentViewport reads that deleted field.
The unrelated MCP decision screen's state was not part of this family.

## Native contract

At the exact declared Textual revision `d7337ee084f6dcda42cbd8a41c7417e87d60ae78`:

- WorkerManager owns acquired worker membership and starts the worker once.
- Worker._start publishes the original task/completion callback.
- Worker._run suspends before invoking the supplied `_reconcile` work.
- Worker.cancel and Worker.wait own cancellation and joined terminal outcome.
- Worker._context supplies the exact worker returned by get_current_worker.

Thus cancelling during native startup need not enter `_reconcile` at all.
Suspension's original handle revocation works in both cases; a second running
flag no longer survives that joined cancellation. A departing reconciliation
also cannot clear a subsequently admitted worker's handle. This fixes a
source-supported lifetime counterexample, not an attribution of an existing
UI/performance failure.

## Source evidence and remaining acceptance

`OWNER-CONSUMERS.json` records before/after declarations, writes and readers via
the existing refactor-audit Package. All288 production/398 test modules parse
with zero omissions; unchanged modules reuse their original parsed trees. The
exact native dependency was already parsed249/249 with zero omissions. Changed
modules compile without importing the application. Only DocumentViewport's
constructor, request and reconciliation method change; suspension, resume,
close, budget, body materialization and all other methods are AST-equal.

No App/test execution, build, prefix, native keeper or provider operation was
performed. Future affected acceptance is one mounted same-source cancellation
before reconciliation entry, followed by resume/coalesced demand and joined
close through the existing App/Worker owners. It needs an explicitly eligible
purpose; no old project/prompt/renderer or whole workflow journey repeats.
This draft is not installed Ready and does not close whole TC1 or460.
