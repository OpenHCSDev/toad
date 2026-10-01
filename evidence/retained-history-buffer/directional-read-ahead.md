# Directional native read-ahead continuation

Integration owner: Heisenberg, PR254. Contributor: Kepler.
Base: merged PR257 `4e1bae042b461d6d12cce7e0c445250b42bb1c22`.

The retained original41MB physical/profile evidence remains authoritative.
`candidate01/capture/foreground-cost-stacks.json` joins complete sampled stacks
to the original native phase clocks. Layout/native paint are the largest
observed Toad stack category (35–50 workspace timer groups during each held
phase). These are compressed transitions, not CPU time or sample counts.
Heisenberg owns that reader/layout investigation independently.

## Concrete preparation defect

`MovingPreparation.neighbors` and `body_order` own incoming direction, but the
same demand inherits `PreparationDemand.edges` returning both page cursors.
`TranscriptSourcePreparation.prepare_scroll` uses those edges verbatim and
`TranscriptPageBuffer.prefetch` reads each eligible edge every round. Moving
forward therefore still reads and prepares pages behind travel; moving backward
does the converse. This consumes the existing model/render admission and can
compete with foreground demand without providing incoming runway.

Add the missing directional hook to the existing MovingPreparation member.
Stationary demand keeps its two-sided reserve; Destination demand keeps its
direct jump with no intervening edge traversal. Reversal retains original
demand identity revocation. No new task, scheduler, store or cache.

Pattern: IMPL-4, half-finished family. Shared consumers remain unchanged.
Measure actual source requests and native demand in the existing source pilot;
use one affected original saved-source physical journey with same-run profile.
No unchanged baseline recapture, provider call, public read, owner restart,
package mutation, or publication/Conversation edit.

Scope remains source correction and physical assessment. Global CPU, reader
discontinuities, full3x buffer guarantee and installed ACP/default readiness are
open under the existing owners.
