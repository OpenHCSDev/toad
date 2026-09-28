# Navigation regression handoff — 2026-09-27

Base: Toad `447afa6ed791bbde6336cafded8721867b700aef`.
Owner: the Sagan/McClintock navigation worktree,
`fix/navigation-validation-20260927`.

## Implementation

`CommsSidebar` owns readiness and projects the app's existing `SidebarState`.
Route validation can temporarily hide a newly rebuilt roster. Completion used
to restore its saved scroll against that hidden roster's zero scroll extent,
then declare readiness. The subsequent reveal painted the top of the list and
could no longer restore navigation. The failure reproduced after readiness,
including a saved offset of 12 clamped to zero.

Completion now requires the roster's own display flag, flushes its pending
layout invalidations, measures the rebuilt tree, and commits the restored
viewport before setting readiness. These synchronous operations share a paint
batch. Successful route validation schedules completion after revealing the
roster. The existing route checks and sidebar state authority are unchanged.
Duplicate completion callbacks do not repeat the transaction once ready.

The inherited readiness-aware frame instrumentation is retained. The sidebar
pilot also forces completion ahead of queued layout work. It asserts that both
hidden-roster completion and a visible roster with an insufficient old scroll
extent were exercised, and retains exact ready-frame, scroll, expansion,
selection, hover, and native-view assertions.

The allocation pilot's `retained[row.thread_name]` lookup assumed hidden rows
survived. Hidden presentation retirement intentionally discards those rows.
Its shared many-tab fixture now requires empty retired trees, reconstructs the
complete expected thread set, verifies closed and still-open routes, and checks
object identity across an unchanged refresh of the active presentation. Tab
order and unsent drafts remain asserted. No assertion bypass was added.

## Validation

Test interpreter:
`/home/ts/.local/share/agent-comms/runtime-current-forks-20260927/bin/python`.
Installed dependency metadata verified Textual
`4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e`; `PYTHONPATH=src` selects this
worktree's Toad. No dependency pins or installed packages in that runtime changed.

Both original failures were reproduced. The forced-order sidebar regression
also failed against the original implementation. Final production code passed:

- `sidebar_navigation_pilot.py`: three normal and three forced-order runs;
  another `--finish-before-layout` run passed with the explicit coverage assertions.
- `navigation_allocation_pilot.py`: the 40-peer, 12-channel, ten-opened-tab
  workload, all navigation and retirement assertions, and measurement census.
- `sidebar_projection_pilot.py`, `sidebar_opening_state_pilot.py`,
  `sidebar_pointer_focus_pilot.py`, `sidebar_layout_controls_pilot.py`,
  `navigation_source_timer_pilot.py`, and `history_scroll_frames_pilot.py`.
- `git diff --check` and the NRA recipe replay described below.

Commands use `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src`, and a private
`TMPDIR=/home/ts/.cache/toad-navigation-fixes-20260927/tmp`. Individual pilots
have a 60-second timeout; allocation has 165 seconds. Logs and raw NRA reports
are in `/home/ts/.cache/toad-navigation-fixes-20260927`. Fixture directories
and test-owned workers are cleaned by `runtime_fixture`; the private temporary
root was checked empty after testing.

These are local headless correctness results, not live terminal latency,
installed-candidate, backend, paid-model, or CI results. Parent retains live
installation/backend ownership; PR #73 remains separately owned. Next action:
review this draft and let the parent decide integration and runtime validation.

## NRA scope and proof limits

Used the required `nra-refactoring` skill. A private Python 3.14 NRA environment
was needed because the existing NRA environment's Python 3.11 cannot parse
Toad's type aliases. Full contextual scans before and after cover 435 Python
files across Toad and the pinned Textual dependency, with reported findings
limited to `comms_sidebar.py`, `session_view.py`, and `app.py`. Both completed
with two reported semantic-boundary findings; these are not a clean global
architecture verdict. The full report does not emit detector omission counts.
The separate cached loop explicitly reports partial coverage: 43 detectors
analyzed, 36 omitted. An initial 20-second scan hit its deadline; the completed
scans used a 150-second budget.

Production edits were simulated and applied with NRA revision-checked exact
target patches. [recipe.json](recipe.json) consolidates the final two method
changes against the base revision. Its replay is parse-clean, leaves the input
snapshot unchanged, and exactly reproduces final production source. These
authored lifecycle bodies have no native behavioral-equivalence proof or
architecture guards; the executed pilots establish the stated behavior.
The semantic decision belongs to `CommsSidebar`, rather than a new registry,
state mirror, or framework policy change.
