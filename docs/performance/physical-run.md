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
