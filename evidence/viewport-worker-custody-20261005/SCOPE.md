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

## Prepared single affected mounted mode

The existing `viewport_body_lifetime_pilot.py` now accepts
`--worker-custody-only OUTPUT`. Its old main and settling helper are AST-equal
to the source checkpoint and are not invoked by this mode. The installed App
borrows the original runtime fixture and installed CSS, a fresh private root
beneath the owned output, and the original mounted window/frame admission.

A temporary profile observes only entry into that exact owner's original
reconciliation method and its native worker identity; it chains and restores
the preceding hook. No method, worker scheduling, renderer or input is replaced.
The control cancels and joins a pre-entry worker, resumes the same source and
checks three requests retain one worker, then closes and joins the currently
admitted worker. Completion may release further legitimate frame demand; it
does not require a global idle interval or discard another worker's custody.
The original App/preparation/runtime teardown completes before scratch removal.

`PROPOSED-MOUNTED-CONTROL.json` supplies the literal installed command tail,
working directory, environment, control SHA and planned output. It appends only
test helpers after installed application paths. The actual interpreter, source
wheel cohort and execution purpose remain explicitly unbound. Heisenberg owns
that joint binding and his unrelated observer-navigation correction. No separate
environment, build, old journey or currently authorized App run is implied.
Control and command compilation pass without application imports; App UNRUN.

## Normal source wheel prepared

Parent authorized one normal cached Hatchling 1.28 build from frozen `7ecec607f9723d4f1747494564dd7b1b174b2180`. Heis confirmed no matching retained full319 artifact. The original builder completed once in 0.669424585s; no environment, dependency resolution, package installation, App or native operation.

Wheel `b2e420e5b2eed1aaa96d815b2abf38f990272a047417c2ca5082c01d9149a151` has all319 Git/local/ZIP assets exact and all324 RECORD entries verified. Full metadata hashes and declared Core/Text/Diff pins are in `wheel-proof.json`; only original `viewport_body.py` differs from reviewed main465 and318 packageassets remain equal. Literal wheel remains in owned `.artifacts/viewport-worker-custody-20261005/wheel/`.

The control085b/proposal20c7 are unchanged. Eligible installed interpreter and Heis final joint source/pin/fullwheel relation remain unbound. No installedReady claim. The observer-only usefulpaint successor can qualify its retained7f wheel independently; this new466 artifact does not hold that work. Heis owns future normal worker integration and explicit one-control operator handoff; there is no slot reservation or additional runtime authority.
