# PR116 independent thread-panel lifetime slice

## Ownership

PR116 published head `4dea0d6ea7f5b2f5dff518d869f9ffccc8553a4b`
and dispatch111 reserve workspace/session presentation ownership for the110
investigation agent. Its tree at `~/wt/toad-navigation-allocation-20260925`
contains unpublished production/test/audit edits. None were changed or copied.
The current comms ledger is empty; active registered threads do not identify a
116 worker, and the current channel history search contains no116 handoff.
The existing PR claim is preserved; current agent activity is not verified.

Sol owns only demand-built session thread panels in
`~/wt/toad-session-panels-sol-20260928`, branch
`perf/session-panels-sol-20260928`, based on the entire published116 head.
Ownership/scope was posted on116 and exact integration interface on120 for
Carver, who owns120/121/123/124 integration. The owner authorizes finishing and
merging through the parent; the original116 implementation-only hold is obsolete.

## Code and deletion closure

- `SessionThreadSidebar(SideBar)` owns rich Thread/Comms/Plan/Project/Recovery
  construction on actual first reveal, for every session kind. MainScreen's
  eager panel construction is removed. Hidden sessions create none of these
  widgets, subscriptions, or panel tasks. The ordinary inherited hydration and
  navigation owner still handles mount, controls and geometry.
- Current project/thread identity is read at hydration, then synchronized after
  mount. Existing operational Conversation/ACP lifetime and original editor are
  unchanged. Revealed widgets are retained; pane closing cannot discard project
  tree selection, scroll, or sidebar state.
- MainScreen's ACP plan caller now supplies existing typed `Plan.Entry` values to
  `update_plan`. Only the latest presentation state is retained, not buffered
  events. Plans received while panels are absent and updates racing hydration
  are reflected at mount. No parallel ACP decoder/schema/store was added.
- Queued hydration rechecks the nominal sidebar's reveal state. An actual
  cancelled-reveal regression failed before this fix (`race-before.log`).
- Removed generic `defer_until_reveal` mode/field and all remaining callers.
  The nominal session-sidebar subtype owns that behavior through inherited
  hydration hooks. Removed `defer_thread_panels` and
  `hydrate_thread_panels_on_reveal` from both lifetime cases and their ABC.
  Keep116's `SessionSurfaceLifetime` name, retiring the forbidden old ABC name.
- Unchanged shared per-class ratchet reports **zero positive deltas** at source
  `49bad3b`: MainScreen -13, SideBar -3, each lifetime case -6. New sidebar
  declarations are reported by the ordinary tool, without added exemptions.

## Actual evidence

Production imports come from a **noneditable installed wheel**, not PYTHONPATH.
`evidence/session-panels/installed.json` records dependency provenance:
core `2bfbdb23`, Textual editor-state feature `d9def32f` inherited from116.
This does not claim current live pins, latest-main integration or model compaction.

Final installed retained-session pilot (`retained64-nominal.json`):

| Retained tabs | RSS MiB | Async tasks | Constructed rich panels |
| --- | ---: | ---: | ---: |
| 4 | 110.6 | 534 | 0 |
| 16 | 132.1 | 1628 | 0 |
| 32 | 161.8 | 3084 | 0 |
| 64 | 221.7 | 6000 | 0 |

Completed in23.93s. Original document/EditHistory identity, undo, draft,
Conversation task, and revealed panel identity survive switching. Latest plan,
project and identity display correctly on first reveal. A real shell command
completed while its retained session was inactive, using the same shell owner.
This is structural/resource evidence for the independent slice; the6000 retained
tasks make clear that the global rich-session lifetime problem remains.

Final **native terminal**16-session pilot (`native16.json`,
`native16-nominal-runner.json`, raw `native16.ansi`) exits0. Linux PTY driver,
real physical `NATIVE` bytes received/rendered by the actual editor, same mounted
state and shell assertions. No Agent.start, wire read, renderer, or editor mock.
No provider prompt was sent: real model-backed ACP retention is not claimed.
Reproduce with `python evidence/session-panels/native_runner.py` in the own tree.

Four focused ownership/TL0 guards pass (`focused-final.log`). The broader five
case guard attempt has **one existing false-positive** (`guards.log`): the shell
activation guard rejects `app.settings.shell` in initialize_view even though it
is settings access rather than `self.shell` resource activation. The116 owner's
unpublished test already corrects that exact distinction; that edit was preserved
and not duplicated. No full-suite green claim. Setup import failure and expected
race failure receipts are retained; later results do not erase them.

## Remaining PR116 work

110 investigation itself is complete; its runtime acceptance belongs to116.
116 still needs a persistent workspace/selected-surface boundary for all kinds,
a global bound on inactive **already-revealed** rich presentations, operational
ACP/queue/permission updates preserved during retirement, exact final pins,
matched 4/16/32/64 tail/input/resource measurements and affected/full-suite
failure closure. This slice does not replace its owner's controller/pool work.
Revealed panes are deliberately retained until that state-preserving boundary
exists. No default-off feature or compatibility path was introduced.

No live route/root/launcher/install changes, CI wait, provider calls or predecessor
edits occurred. Parent owns merge/integration and live activation.
