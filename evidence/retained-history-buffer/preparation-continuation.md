# Viewport preparation continuation under PR254

Integration owner: Heisenberg. Contributor: Kepler. Start source: f0534038,
including whole-window restoration and the merged directional native read-ahead.

Scope: actual measured viewport demand, retained prepared/rendered body resources
and unnecessary foreground preparation. Trace original native source reads,
viewport admission, shared worker preparation, materialization, layout and paint
before editing. Heisenberg alone owns workspace/restoration changes.

Use one existing private native-journal/source physical capture with held
Up/Down/reverse/End/idle and actual warm A/B/A editor/reader retention where the
existing workspace fixture supports it. Preserve the authentic protected41MB
resource and native uncertainty. No provider calls, owner restarts, installed
package changes, public bus, alternate registry or semantic state mirrors.

The retained profile shows repeated native layout/extent/style work during
scrolling, with74–78% UI CPU. These observations identify a crossing to inspect;
compressed GIL transitions do not supply CPU attribution. End/idle is readable
on the earlier scope; f053's final whole-window extension has source evidence
only and must not inherit that earlier physical result.

Existing PreparationRuntime, DocumentViewport, body reconstruction and native
Workspace/SessionAdmission own behavior and resources. Extend those contracts
and delete unnecessary consumers in place. Report concrete changed files,
deleted lines, actual physical limits and next remaining cause. Ship useful
code before the final performance target.

## Concrete original-demand custody correction

`DocumentViewport._reconcile` selected ahead bodies from the current demand,
then awaited foreground restoration/retirement before capturing the demand
used by the existing speculative `accepts` checks. A reversal during that
await therefore authorized old-direction neighbors with the new demand.

Capture the existing demand before selecting its neighbors and preserve that
same reference through the admission. Same-direction updates retain their
original demand; reversal already replaces it and stops speculative work.
No added state, flag, cursor, store, worker or lifecycle mechanism. Native
foreground-required bodies still restore; the pending viewport pass selects
the new direction through the existing worker. This closes a declaration-owner
bypass (BOUND-2) rather than introducing another revocation path.

Actual changed-source physical acceptance is pending the single coordinated
source capture; do not treat this source checkpoint as installed readiness.

The original native counter is now RED/GREEN. The old f053 viewport implementation
passes the newly current demand to acceptance after real PageUp reversal;
`demand-custody-red.json` records `original_demand=false, accepted=true`.
The corrected source retains the original reference and rejects it:
`demand-custody-green.json` starts `original_demand=true, accepted=false`, then
accepts the new native direction through the same resource worker.

`tests/viewport_demand_custody_pilot.py` runs the actual ToadApp, native Markdown
body, original viewport worker and actual driver Key route. Its observer holds
after original foreground restoration completes, before the awaiting caller
continues. It does not replace bodies, records, protocol or UI. Earlier control
failures stay documented in `demand-control-negatives.json`. Original RED log
and GREEN receipt remain in owned persistent scratch; no provider was invoked.

The existing physical pilot can now seed a second actual MainScreen through
SessionAdmissions and read the same protected native journal under its own
declared private Thread. Each loader is bound to its original native Window,
so hidden-view reads cannot be mislabeled as the selected view's demand.
WarmSourceJourney extends the existing WarmScrollJourney peer-click hook,
using the captured native peer tab rather than starting an ACP owner. All
scroll, End/idle, A/B/A, draft and Undo checks remain in the same journey.
