# TC1 remaining source at main465

Determining main: `cac7268a733f62f6db57580fd63b64abd52be359` (merged465).
Original requirement: `TC1-workspace-state.md` in the cleanup integration checkout.
This is source evidence, not a new installed or performance qualification.

## What is already implemented

| Original module | Current owner and consumer result |
| --- | --- |
| `session_presentation.py` | `OperationalSessionPresentation.acquire` owns construction, pre-binding, mount, editor/reader restoration and attachment. `NativeSessionSurface.widget` derives from its admitted presentation. Logical selection and native resource custody remain distinct. Accepted461 pending input custody is preserved. One budget seam remains below. |
| `transcript_publication.py` | Each `TranscriptPublication` retains its actual actor, source generation, window, contents and captured resources. Its async application/read/prepare/mount consumers check that same custody. `TranscriptPresentation.histories` derives from native direct children; retirement joins original workers/resources. No additional stored canonical-history pointer was found. |
| `screens/workspace.py` | Commands, root and focus target ask `WorkspaceSource`; loading/shown/parked/detached selection lives in `WorkspaceSessions`. Layout reuse asks `WorkspaceLayout`; frame and body admission ask their original presentation owners. Native geometry/style revisions are observations, not another selected-session store. |
| `terminal_execution.py` | `TerminalOperation` owns start, acquired PTY, cancellation and retirement; `TerminalCompletion` retains original child outcomes. ACP output/wait, TerminalTool, CommandPane and Shell ask these owners. The old independent process/task/return-code classification is absent. External ACP optional exit status and native weak-view collection remain legitimate boundaries. |
| `transcript_source_preparation.py` | `TranscriptState` owns reserve, deferred mutation, park/resume and final preparation retirement. `HistorySourceSnapshot` fences the original generation/window/screen/source. Saved, projected and wire history consumers share it; prepared page storage belongs to its original runtime scope. |
| `widgets/project_tree_intent.py` | Accepted454 restoration remains with ProjectPanel/ProjectTreeIntent and native DirectoryTree. No reopened implementation or acceptance work. |
| `widgets/viewport_body.py` | BodyMeasurement's Live/Measured/Rendered/Materializing members own body readiness, paint, extent and publication custody. ViewportPresentation owns frame membership; DocumentViewport owns the warm set. One worker-lifetime seam remains below. Accepted458 renderer work is outside this pass. |
| `workspace_chrome.py` | Sidebar placement actions live in `SidebarPlacementAction`/`SidebarLayout`; chrome derives geometry and native ordering. `on_sidebar_action` delegates to that owner. Navigation capture/restore and selected wire observation retain their existing owners. No competing placement implementation was found. |

## Genuine remaining source seams

### Inactive presentation resource admission

`NativeSessionSurface._trim_retained` (`session_presentation.py:254-280`) reads
`DocumentViewport._warm` directly and repeats the widget/byte admission loop.
It sums only `retained_source_bytes`. `PresentationBudget.admit`
(`presentation_window.py:70-84`) already owns admission and includes original
`retained_paint_bytes` as well. BodyMeasurement/RenderedBody own those bytes;
DocumentViewport owns warm membership and release.

The complete deletion belongs to those existing owners: expose the viewport's
actual retained resource cost through the presentation and let the original
budget admit ordered inactive presentations. Remove the foreign warm-set
interpretation and duplicate thresholds. Preserve selected/required custody,
tab recency, native descendant cost, dead weak references and source data.
This is an incomplete source-accounting relationship, not a measured memory or
CPU failure.

### Viewport worker cancellation before entry

`DocumentViewport.request` (`viewport_body.py:983-989`) sets `_running` before
creating the original worker. `suspend_source` (`1021-1036`) clears, cancels and
joins `_worker`; only `_reconcile`'s `finally` (`1166-1167`) clears `_running`.
The pinned Textual worker (`d7337ee`, `worker.py:378-409`) suspends before
invoking its supplied work. Cancellation at that point never enters
`_reconcile`, leaving `_running` true after the worker has joined. A resumed
request can then refuse a replacement worker.

The complete repair belongs to DocumentViewport's request/reconcile/suspend/
resume/close family: original worker custody owns whether work is admitted;
delete its copied `_running` decision. Keep pending demand and source suspension
as distinct facts. No new timer, retry, worker wrapper or native patch is
justified. This is a source-supported counterexample, not an attribution of an
existing recorded UI failure.

## Coordination and limits

Both seams were sent directly to Heisenberg, the sole TC1/workflow and460
integrator, with exact owners and deletion proposals before any shared edit.
Neither is an independent disjoint write family. No production change was made
without that seam agreement. Existing source branch and frozen460 remain intact.

The original syntax threshold is still undefined for the seven files absent
before129. This pass does not manufacture a baseline or claim whole TC1 done.
Configured continuous workflow, loaded-history cohorts and physical performance
remain Heisenberg's separate acceptance work. No old audit, test, build, App,
installed package, provider or native keeper operation was repeated.

Original refactor-audit `Repository`/`Package` parsed all288 production modules,
398 test modules and249 modules at the exact declared Textual dependency with
zero omissions. The eight owner modules contain53 class declarations. Relevant
imports, inheritance, writes, decisions and consumer sites were indexed once;
name collisions such as unrelated Command classes were resolved by their
imports. Dynamic framework dispatch and weak/native lifetimes were read
semantically; AST coverage is not behavioral proof.
