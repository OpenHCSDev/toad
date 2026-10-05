# Preparation completion on its original worker

Source successor to the frozen workspace 455 cohort. Heis owns workspace
integration; Kepler owns native compositor and scroll geometry. This seam is
the existing preparation work family in `work_preparation.py`, plus the sole
asynchronous page-work execution override in `transcript_preparation.py`.

The original runtime dispatches a thread work's pure preparation, retained
representation, and key byte accounting separately. Fresh reusable thread
reads therefore cross three worker admissions before delivery. Renderer and
asynchronous page results cross two after their own execution. The work
declaration can complete its result and accounting together; the runtime still
owns admission, storage eviction, waiter cancellation, and shutdown. Each
foreground consumer still receives an independent worker-materialized value.

The source pass reads current 455 `bc611f6e` opening, frame, viewport, source
lookahead, Markdown, render, and preparation consumers. Original retained
body-frame profiles contain preparation/materialization stack observations;
their transition groups are neither durations nor proof of current latency.
The older painted-tab matrix remains above the requested latency goal. This
change makes no speedup or useful-first-paint acceptance claim.

Before editing, the original audit Package parsed all 288 production modules
at the joint source without omissions. All production ThreadWork leaves use
the existing `prepare` hook. All renderer leaves use RendererWork. The sole
other PreparationWork execution override is TranscriptPageWork. Current open
Toad PRs contain no edits to these two files. Exact seams were sent directly
to Heis; the native geometry boundary was sent to Kepler.

## Published implementation

Product `ec10e2eb` changes the existing work execution contract to return its
completed `PreparedValue` and retained size. `PreparationWork.finish_result`
owns representation and key accounting. ThreadWork calls it in the same
worker that calls its original `prepare`; RendererWork calls it after its
original renderer result. TranscriptPageWork forms and measures its original
page in that same completion worker. The sole runtime execution consumer
admits the completed result to its existing bounded cache.

Source-declared completion dispatches, excluding unchanged identity and
independent delivery calls:

| Fresh result | Before | After |
| --- | ---: | ---: |
| Retained ThreadWork | 3 | 1 |
| Unretained ThreadWork | 2 | 1 |
| Retained renderer result | 2 | 1 |
| Prepared page, after fragment delivery | 3 | 1 |

These are call-path facts, not measured speedups. No runtime or work class,
storage representation, cache, limit, admission lane or state flag is added.
No former execution API remains alongside the new contract. The original
cache retention decision and final delivery scope/shutdown checks remain in
PreparationRuntime; each waiter still borrows the admitted task, and every
consumer still materializes its own mutable value on worker delivery. An
already executing thread now owns its complete pure result through shutdown;
the existing runtime/delivery checks still refuse publication after closure.

Original audit Package parsed all 288 production modules before and after
without omissions. Both changed modules compile; diff check passes. Original
debt census reports zero positive structural measures, 21 added code lines.
The failed audit attempt using unsupported revision `WORKTREE` and the first
census invocation missing its JSON output argument executed no product code;
the final source census uses the committed product revision.

## Original source policy checks

The first serial batch attempted the three unchanged original controls once.
All three failed during import in about 0.22 seconds: Core's native resource
loader requires a filesystem path, so its wheel ZIP cannot be a source
runtime dependency. No policy case ran. Original logs and commands are
preserved in `source-sanity01`; no product defect is inferred.

Parent authorized one corrected batch using the existing Core filesystem
source root. All 355 assets match the original retained Core 0ed wheel,
including its resource declarations; the cached registry 0.2.1 and ACP 0.12.1
meet the source contracts. The loader's original resource rule is preserved.
The three unchanged controls passed once, serially:

| Original control | Exit | Seconds | Scope |
| --- | ---: | ---: | --- |
| work_preparation_pilot.py | 0 | 2.472 | Sharing, copies, revision/eviction, independent lanes, cancellation, shutdown |
| work_preparation_delivery_pilot.py | 0 | 2.137 | Fresh/cached retirement, delivery drainage, queued-worker rejection |
| serialized_preparation_pilot.py | 0 | 2.185 | Graph release, independent deliveries, byte bounds, scope retirement |

These are source runtime-policy controls with the original Backend double.
`source-sanity02` preserves exact commands, hashes, stdout/stderr and joined
subprocess outcomes. This is not an installed application, renderer-process,
SDK, native-input or speed proof. No dependency installation, environment,
prefix access or native artifact execution was used.

## Remaining acceptance

Installed page/body behavior and useful-first-paint/fast-wheel acceptance are
**UNRUN**.
The existing preparation, serialized preparation, delivery retirement and
page lookahead controls cover sharing, isolated mutation, shutdown and source
revocation. A future affected installed application check should exercise
native Markdown/fragment delivery and wheel/reversal using the normal joint
workflow cohort, not repeat frozen 454 or accepted Explorer controls. The
existing Markdown return pilot has real mounted body/cache/file-link
assertions; its helper, settings and cleanup operands must be reconciled to
the eventual admitted source before execution. No new purpose is assumed.

No application, package installation, native process, provider, input, or
recording has run for this successor. Frozen 454/455 controls, artifacts, installed
cohorts and public runtimes remain under their original owners. Heis retains
the complete workflow/performance objective; this source change removes one
concrete preparation cost and does not finish that objective.

## Proposed affected application

The existing `markdown_return_reuse_pilot.py` now has an optional page/wheel
phase in the same original App. It borrows the existing installed CSS helper,
keeps the mounted cold-Markdown/ABABA retained syntax and fresh file-link
checks, and adds actual async page delivery, the production filter ThreadWork
projection, native wheel/reversal/End, reader admissions, editor Document/undo
and source retirement. The original application owns its renderer shutdown.
Typed authored pages are not saved native history; native Pilot input is not
physical UI recording. No speed target is claimed.

`PROPOSED-PAGE-BODY-WHEEL-OPERANDS.json` names the literal future command,
output, helper hashes and scope. The control parses/compiles; App execution
is **UNRUN**. Heis must bind the normal joint source/filewheel and an eligible
issued holder purpose before execution. No frozen 455 control, existing
installed prefix, native geometry owner or accepted Explorer journey changes.
