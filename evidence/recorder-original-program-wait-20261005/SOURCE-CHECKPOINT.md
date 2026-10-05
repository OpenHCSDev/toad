# Original program wait: source checkpoint

## Concrete counterexample

Original Heis06 delivered CtrlQ at `711152.228939581`. The original UI
parent sent SIGTERM at `711155.294319825`, after the recorder's separate
three-second wait. The interaction deadline was `711170.788536485`:
18.56 seconds remained at delivery, and 15.49 remained at forced retirement.
The finish deadline was `711186.788536485`, with the existing 16-second
finalization reserve. UI returned -15 and st returned 1. The whole original
job timed out at 150.143211631 seconds. None of these outcomes is relabelled.

The latest retained application export predates CtrlQ. These records prove
the recorder's early forced retirement; they do not prove application quit
admission, preference saving, graceful close, or its cause of delay.

## Existing owner and deleted decision

`OwnedProcess.wait_for_exit` now accepts the caller's absolute deadline.
`TransferredGroup.wait_for_exit` observes the child and then its original
parent within that same deadline. `record` supplies its existing interaction
deadline for graceful quit, deleting its independent three-second allowance.
It joins st and st's original parent within the same remaining budget before
cleanup, preserving the terminal's natural exit after the UI parent finishes.
The child-already-gone path in `TransferredGroup.stop` derives its parent join
from the existing retirement grace instead of a separate literal.

The transferred identity remains an observer. `ProcessOwner.launch_program`
retains its actual `Popen.wait`, finalization, original child outcome and
publication; `launch_terminal` retains st's actual parent wait. Neither
method changes. A detached observer still cannot supply a parent exit code.
`require_successful_exit` still refuses missing or mismatched parent receipts,
signals, parent errors, cleanup failures and unsuccessful original outcomes.

The interaction budget and finalization reserve keep their distinct purposes.
The configured duration is unchanged. The outer driver starts its bounded job
before display/UI acquisition, while the recorder starts its internal budget
after acquisition. This source change does not reconcile those different
start points or claim to fix the original whole-job timeout. Heis owns that
workflow budget and the application shutdown family.

## Complete source family and limits

The original `audit.findings.Package` parsed 288 production, 398 test and 40
tool modules at this branch's base, with zero omissions. The attached receipt
lists static imports, literal recorder paths, every recorder wait declaration
and call before/after, and unrelated terminal API calls separately. The known
dynamic recorder loaders and outer `history_edge_scheduling_pilot` caller were
read. Arbitrary externally selected modules and computed argv cannot be fully
resolved by this static pass.

Core `ProcessIdentity`, `Platform.matches`, `ObservedProcess`,
`ParentedProcess`, and synchronous retirement were read as the original custody
contracts; the original Core Package parsed all 324 production modules with
zero omissions. Exact incarnation observation does not replace actual parent wait.
This is the existing process mechanism carrying its callers' work (IMPL-13);
no new process type, timer, outcome mirror, guard or compatibility alias is added.

Heis's newer `publish_program` launch timestamp is disjoint and must be retained
when this narrow diff is adopted into his successor. His application lifecycle,
preferences, workspace/session shutdown and preparation files are untouched.
MCP draft #472 remains separately published and unfinished; frozen #468 and
all original06 helpers remain unchanged.

## Qualification

Source compilation and diff checking only. No recorder/application import,
test, OS/UI/native/SDK/provider/input, prefix operation or original06 retry.
Original receipt, guardian publications and offline evidence stay in their
original paths; this receipt retains their hashes without duplicating raw data.

Future affected acceptance belongs to Heis's separately authorized continuous
workflow successor: original CtrlQ admission and application close, original
UI/st parent outcomes without owned signals, cleanup and outer bounded result.
It is **UNRUN** for this change. Prior accepted OS/ordinary/profile controls do
not qualify the changed quit wait, and need not be repeated.
