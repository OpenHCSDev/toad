# Isolated physical Toad runs

The shared implementation is `tools/physical_ui.py`: the existing
`XvfbDisplay → OwnedDisplay` family owns Xlib/display allocation and retirement;
`TerminalApp` owns st, the frontend, source observations and all physical input.
`tools/acceptance.py` and the scrolling scenario consume it. There is no public
raw-input method on a display.

## Entry point

Run with the **installed source runtime's Python**, with Core's retained
`CheckRoot.create()` and `SuppliedRuntimeHome` APIs available (Core PR #3821).
Do not put the candidate Core checkout on `PYTHONPATH` and call that installed
source qualification.

```sh
/home/ts/.local/share/agent-comms/current/bin/python \
  tools/performance/scroll_scenario.py \
  --thread YOUR_THREAD --history-thread ANOTHER_THREAD \
  --output /home/ts/.cache/agent-scratch/YOUR_OWNER/fresh-run
```

`--runtime /absolute/complete/candidate-prefix` selects only the frontend and
private copy's runtime. The source controller remains installed. The candidate
must contain its own Toad/Core/Textual packages; a dependency `.pth` pointing
those packages outside the selected prefix fails actual module-origin checks.
Supply a new output directory for each distinct run. Do not replay a failed or
UNKNOWN input against an old run. Terminal dimensions are **cells**; framebuffer
sizes are **pixels**. For the mobile48×48 →140×40 journey, supply
`--columns 48 --rows 48 --framebuffer 1600 1200 --resize 140 40`, or pass
`framebuffer=Size(1600, 1200)` to the callable factory. The owner checks actual
native window bounds and rejects clipping instead of recording half a terminal.

The callable entry point is `TerminalApp.copied(source, threads, runtime,
output, thread=..., size=Size(...), framebuffer=Size(...))`. Its context yields the admitted app and
retains the copied root, frontend-home, operation receipts, screenshots and
recording on exit. The caller still owns retiring those retained files after
acceptance and actual borrower checks.

## What the owner establishes

- `CheckRoot` alone selects/imports bounded stopped history; old goals, turns,
  tasks, processes and input authority do not travel with it. The installed
  source owner creates history; only its disposable copy is published through
  `RootRuntime.publish` to a supplied runtime.
- Fresh Toad config/state/data and no copied saved-tab database. Presentation
  settings derive from the declarations on the `INTERFACE` page; session/shell/
  launcher settings and the original anonymous identity do not travel. Collection
  is disabled through `SavedSettings`. The optional palette is copied/validated
  through `WalFile` and the actual private palette directory is observed.
  Source identities cannot be repaired by rewriting tabs.
- HOME/XDG inside `st -e env`: st itself resets HOME from passwd before exec.
- Xvfb uses displayfd, not a guessed display number. Xlib checks its actual
  local peer UID/process; the run verifies the allocated server incarnation.
- Child exec grants debugging only to the recorded controller PID and its
  descendants. It changes no global ptrace policy and needs no sudo. The
  controller owns one bounded operation-source snapshot for its entire Python
  lifetime; editing the checkout cannot change an already started run's wire.
- Before physical input: the actual frontend incarnation, runtime and loaded
  Toad/Core/Textual module locations, HOME/XDG/database, selected/opened source,
  every saved entry's source and every borrowed ACP process's creator/session
  agent coordination roots. Pending/foreign sources refuse input.
- The read-only observation asks `ToadApp.running_app()` and the actual screen
  owner. A window caption is not readiness. `remote_exec` receives an explicit
  module filename binding and an adjacent FieldCodec request; a missing or
  timed-out result is not a successful observation.
- st text travels with the actually published history viewport geometry.
  `ScreenCapture` clips through Textual/Rich's cell geometry, not sidebar
  separators that disappear when a sidebar closes or occur inside code.
  Textual's installed compiled `Region` rejects subclassing; `CapturedRegion`
  adds only the existing `DeclaredWireType` boundary capability and retains the
  actual Region object, without copying its coordinate declarations.

## Runtime input identity (Core #3825 dependency)

The current source requires a `RuntimeResolution` with a recorded interpreter
observation, not just a prefix and three module locations. `RunTarget` retains
that intended build. `AdmitOperation(ObserveOperation)` obtains the actual
process's resolution once at frontend admission through the target-owned probe.
Its `AdmittedResult` belongs to that exact frontend birth; a plain
`ObservedResult` cannot substitute for it. `RunObservation` describes current UI
resources, not a freshly hashed build.
An old build record without interpreter evidence is explicitly unrecorded and
refuses admission. It is not retrofitted by reading its intended executable.

`TerminalApp` owns the admission result with its frontend resource. Every later
observation still checks the actual process, runtime, module origins, HOME/XDG,
database, palette, selected/opened source and all saved/ACP roots before keys.
The declared `FrontendIdentity` groups process birth and primary module-file
paths; equality is derived from that record rather than restating its fields in
two comparison tuples. It must agree with the admission.
Only full wheel/native hashing leaves that repeated callback; there is no
permission flag or product-widget cache replacing those current checks.

A normal exit performs full build verification again and requires equality with
the admitted snapshot before quitting. `frontend/build-admitted.json` and
`frontend/build-final.json` retain the two build observations; ordinary operation
results and `admitted.json` remain current UI/source observations. An exceptional
or uncertain operation still retires without another attachment or input.

The selected candidate must remain immutable during the run. Entry/final disk
checks do not prove that arbitrary intermediate disk mutations were impossible,
and a final refusal cannot undo earlier input. This does not claim continuous
content hashing or complete loaded-code equivalence. Process/root/module-origin
and saved/ACP-root invalidation remain current before every key.

Current observations also carry the actual typed `StorageRule` from the already
observing service's `Registration`. `RunTarget` calls that rule's pure
`require_isolated(root)` observation contract; it no longer repeats the owner's
projection/equality decision. Observation neither constructs a Comms nor writes
a policy. The paired Core must include this API: its `ScopedDirectory` field
declarations own canonical directory checks and future default allocations,
including outward-symlink refusal. There is no fallback to an older API.

Filesystem behavior, registered allocations, persisted reopen and future-child
qualification remain separate prerequisites owned by the isolation work. The
owner's eleven new filesystem cases are written, not run; a source implementation
is not isolation acceptance. Candidate02's Core7e4/Toad620955 artifact pairing
predates this API and cannot qualify the current consumer; preserve it unchanged.

`WheelRuntime` retains copies of its exact inputs under the new prefix's
`inputs/` directory; borrowed originals remain read-only. The package probe
compares every root-wheel member except the installer's rewritten `RECORD`
against installed bytes, then records the verified archive SHA256. Root-layout
wheels are the supported domain; `.data` relocation is refused, not silently
skipped. Remote archive hashes remain metadata, never permission to fetch them.
The deployed donor package probe keeps its existing core-only wire. Updated
built workers derive retained inputs from their own `RuntimeResolution`; the
target subclass supplies explicit inputs before its first resolution exists.
Both use the same verification loop, without changing old workers' request shape.

The interpreter observation keeps the invoked environment separate from the
resolved executable and the native image actually named by the loader for
`Py_GetVersion`. Stable file reads use `FileRevision`; their SHA256 values are
native **disk-artifact** evidence, not complete loaded-code or stdlib-content
equivalence. Repository ancestry remains `RecordedBuildIdentity`'s separate
contract: a verified archive still does not acquire a Git revision.

This implementation is a published source checkpoint, not candidate/carry or
physical qualification. The first prepared candidate remains immutable and
unqualified under the new interpreter requirement. No frontend/native/model
launch follows from the earlier single artifact-preparation approval.

## Evidence limits

This scenario exercises **bounded stopped history**, not the retired shell
benchmark's active provider response. Historical `scroll-series.md` entries
retain their original source/traffic scopes and old API names. They are not
commands to rerun against the live root.

A source observation establishes module **locations**, not hashes of already
loaded code. Screen dumps help inspect text; the continuous Xvfb recording owns
visible pixels. Neither an import nor one screenshot proves the whole journey.
A run with no ACP bindings does not demonstrate the bound/pending/foreign ACP
cases.

The new admission/resource-lifetime split has written model controls for build
admission versus ordinary observation, changed build/process/resources/module
paths, new saved/ACP roots, actual storage policy and source readiness after admission. These controls
are not yet executed. The source/codec checks and eventual candidate preparation
must not be reported as physical or performance acceptance.

Source-observer work is part of the measurement overhead. For example, one
prototype observation took about 97 ms inside the callback before considering
its compilation/dispatch cost. Do not report that overhead as production frame
cost or quietly subtract it from a user-facing latency claim. Correlate complete
controller/call spans and the recording.

The separate reviewed `capture_history.py` path retains its own explicit
approval, identity, size/time budgets and completion token. This entry point
neither starts that capture nor authorizes heap, GC, repaint, remeasure or
arbitrary trace experiments. The legacy `capture_live.py` diagnostic options do
not become authorized merely because they import the shared display resource.

## Current qualification

Core #3821 is installed in 7d0d; the merger reports 23 selected checks passed.
Fresh runs10 and12 used that installed source interpreter with `-I` and no Core
source overlay, and observed all three actual package origins in the supplied
mobile candidate. Run12 completed exit0 through held PageUp/PageDown, reversal,
End and wheel input, with screenshots/recording and typed private-copy stop.
The st, Xvfb and encoder receipts name their exact process births and existing
child-owner outcomes; their PIDs and the frontend were independently absent.
Run13 also completed the48×48 →140×40 candidate geometry journey in a1600×1200
owned framebuffer. There were **no bound ACPs**. Four isolation counterexamples, the wider tab/
resize/arrival journey and actual profiling remain separate obligations.

Run8's foreign candidate-module origin, run9's missing-palette warning and
callback timeout, and run11's first-observation timeout remain retained. A
missing palette was demonstrated, not proved to explain every timeout. Failed
or uncertain operations now go straight to the existing owned-process shutdown;
exit does not attempt another attachment/key. No such attempt is replayed.

Current helpers are `tools/physical_ui.py` and `tools/physical_ui_remote.py` on
PR #1393. Consumers must start a new controller from one published checkpoint,
not combine a live process with a newly imported wire shape. A completed
stopped-history scenario is not bound-ACP or performance acceptance.

## Pager failure retirement

The retained configured-fork attempt failed when multiprocessing spawn re-entered
an unguarded controller. Its `BrokenProcessPool` also exposed a separate pager
cleanup defect; neither is an image verdict and the failed root is not replayed.

`WorkingTranscript.execute` reports a read failure inside the pager Worker.
`TranscriptSourcePreparation.source_failed` immediately revokes its source and
starts `retire_source`. Textual's `AwaitComplete` eagerly schedules the join in a
new task, copying the caller's `active_worker`. `Worker.wait` then rejects that
inherited identity as a self-wait before awaiting anything. The traceback is not
evidence of a synchronous UI stall.

The existing shared preparation base now creates that independent `AwaitComplete`
in an empty native `Context`. Its join needs only the cancelled Worker handles;
it must not borrow the caller's worker or message pump. Revocation, generation,
subscription closure, cancellation, awaited outcomes and error propagation stay
with their existing owners. Textual's genuine self-wait guard is unchanged.
All six pager descendants inherit the correction, including saved, wire and
projected history; there is no per-view exception handler or second cleanup path.

Before editing, the retained NRA parser/syntax/canonical-class query covered
1,533 modules: 9,005 original class declarations, 8,966 canonical projections,
39 unprojected OPEN rows and 190 selected lifecycle sites. The manifest retains
source hashes. This is source evidence, not domain completeness or live binding
proof; external/unresolved bases, dynamic mutation and non-Python behavior stay
OPEN. Actual imported MROs confirm the shared base on the relevant saved-history
classes. The source query uses NRA's existing owners, not another parser.

The existing lifecycle controls now observe original coverage publications and
saved error artifacts instead of replacing our own methods. They cover caller-
initiated retirement, pager-initiated retirement, resume, real self-wait rejection,
and a failed read that retires once without an unhandled cleanup exception.
Both changed Python files compile and the source imports from this checkout.
The exact source head `59d8218a4b70896aa0f8226367202cff035dd411`
passed both app controls: **2 passed in 31.58s, exit 0**, under Core's shared
`TestLease`. The controller asserted the actual Core and Toad source origins
before invoking `tests/textual/test_transcript_lifecycle.py`; the retained log
prints both paths, the interpreter and the acquired lease. Its first attempt
failed before pytest because the controller shadowed an imported module with a
`Path`; that attempt is not a test run. The passing run paired Core's earlier
`a5b` lifecycle source, not its subsequent parallel-reader correction.

Receipts: `pi-commander/heartbeat-publication/pager-lifetime-controls-2.log`
and `.rc` under `/home/ts/.cache/agent-scratch/`. These are app-level lifecycle
controls, not installed or physical acceptance. The affected physical journey,
full isolation counterexamples and production performance measurement remain
open; no failed configured-fork root was replayed.
