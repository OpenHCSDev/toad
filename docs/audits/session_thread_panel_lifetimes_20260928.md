# PR116 independent thread-panel lifetime slice

## Ownership

PR116's live external owner is OpenCode PID3635740, session
`ses_f313e4945ffeDPKKenjqdrDnPD`, titled “textual/toad performance”.
Its published checkpoint `1cb7c74` is incorporated here. Its ongoing PR125
integration in `~/wt/toad-navigation-allocation-20260925` remains untouched.
The current registered `opencode-toad-maintenance` identity is stale/stopped;
one CLI handoff was queued (`ae8e3a690a8a`), with no acknowledged delivery claim.
The owner retains persistent workspace/global presentation/controller scope.
Sol owns the independent sidebar implementation and actual ACP retention acceptance.

Journal attribution identifies PID1872762 as the owner's rich64 two-phase test.
It exited on its diagnostic timeout; its later rich32 service completed successfully.
Neither test is ours and no signals were sent. Our initial process environment
explicitly declares an owned private root, avoiding default-root cutover ambiguity.

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

All five focused ownership/TL0 guards now pass after incorporating the owner's
published6f06384 correction to distinguish shell settings from resource activation.
Earlier failure receipts remain; no full-suite green claim.

## Matched installed native ACP retention

`tests/native_session_retention_pilot.py` extends the existing installed native
fixture through an acceptance callback rather than adding another backend or
codec. One real native Pi owner and one real stdio ACP attachment are fixed across
4/16/32/64 logical presentations. A loopback-only model HTTP endpoint returns
fixture responses; no paid provider, Agent, transport, queue, editor or renderer
method is mocked. Other logical tabs do not claim executing native owners.

At every cohort, the original session receives a held prompt and a queued prompt
while inactive, completes exactly two native calls, then renders the native answer
on return. The same transport read loop, process, owner identity and session remain
live; original Document/EditHistory, draft and undo/redo are preserved. All three
reverse/forward/reverse visit phases run; no phase-only acceptance filtering.
The final painted-answer receipt completed all four cohorts and eight native calls.

Matched baseline6f and candidate share core2bfbdb23, Textuald9def32f and verified
native689. Both use noneditable installed wheels and the same fixed source cohort.
RSS is sampled, summed RSS includes shared pages (not PSS or peak); timings include
20ms headless pilot settling and are not native terminal frame latency.

| Tabs | Baseline UI MiB | Candidate UI MiB | Baseline tasks | Candidate tasks | Baseline panels | Candidate panels |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 141.7 | 139.8 | 570 | 456 | 20 | 0 |
| 16 | 173.1 | 163.6 | 2128 | 1558 | 80 | 0 |
| 32 | 216.6 | 194.6 | 4202 | 3023 | 160 | 0 |
| 64 | 299.1 | 256.8 | 8338 | 5944 | 320 | 0 |

The matched final resource run at64 reduced summed process-scope RSS from818.3
to776.7MiB and settled-switch median from99.25 to83.13ms; >100ms switches fell
from83/189 to8/189. The subsequent painted-answer run also passed all assertions
(64:255.4MiB UI,80.56ms median,3/189 >100ms). These are individual measured runs,
not a stable30–40ms claim. Baseline and candidate logs/JSON, actual ACP logs, the
incorrect initial handshake-task assertion and strict native905 refusal are retained
under `evidence/native-retention/`.

The inherited116 core correctly refused native905 because its package manifest
pins689; this was not bypassed. PR125's current core/native bootstrap contract must
be consumed and this affected path rerun on final paired pins before claiming live
integration. Do not restore deleted migration helpers or compatibility imports.

## Remaining PR116 work

110 investigation itself is complete; its runtime acceptance belongs to116.
116 still needs a persistent workspace/selected-surface boundary for all kinds,
a global bound on inactive **already-revealed** rich presentations, operational
ACP/queue/permission updates preserved during retirement, exact final pins,
matched 4/16/32/64 tail/input/resource measurements and affected/full-suite
failure closure. This slice does not replace its owner's controller/pool work.
Revealed panes are deliberately retained until that state-preserving boundary
exists. No default-off feature or compatibility path was introduced.

No live route/root/launcher/install changes, CI wait, paid provider calls or predecessor
edits occurred. Parent owns merge/integration and live activation.

Concrete global-bound gap at published1161cb7c74: RetainedSessionPresentation
still owns one Screen/Conversation per agent-backed mode. The owner's loaded64
run retained65 Conversations/editors and8703 widgets, and its full run timed out;
its two-phase diagnostic is not full acceptance. The required migration is the
existing Agent target/queue/permission lifetime into a long-lived typed source
controller independent of optional rich surfaces, followed by global admission
and state-backed restoration. That ownership boundary remains with116/parent
and the T2/T5/viewport interfaces; this sidebar slice does not invent a reducer.
