# Projected history preparation

## Working source checkpoint

This successor starts from frozen joined441442 head
`2a844fa34c2370fce4341e788fb4448f83467d1e`. Its source and evidence stay separate
from the accepted single installed441442 App. No holder purpose is open for
this successor.

## Owner and deleted work

`CategoryProjection.project` owns category membership. It replaces only the
prepared fragments and retains the original page, cursors and byte accounting.
`ProjectedTranscriptSource` owns the lifetime of that projection.

Previously `boundary` and foreground `get` projected pages, but both prefetch
branches yielded the upstream/raw fragments directly. The existing
`TranscriptHistory.prepare_scroll` consumer then prepared Markdown bodies
excluded by the active category projection. This is a source bypass, not a
measured CPU attribution.

The source now publishes boundary, foreground and both speculative paths
through its existing projection inside one `_project` operation. That operation
checks original source custody before and after asynchronous projection. Both
prefetch branches also recheck the original demand callback before yielding.
No consumer has to repeat category selection or source custody.

The raw reader still owns cursor advancement, transport rounds and runtime
capacity. Empty projected fragments retain the raw interval. Speculation does
not use the foreground empty-page scan and does not acquire extra pages to fill
an empty category projection. No map, cache, flag, timer, queue or native change
was added.

## Source coverage

`owner-before.json` uses the existing refactor-audit `Package` over all288 Toad,
394 test, 41 tool and249 native59 modules, with zero parse omissions. The relevant
relationships were read through `ProjectedTranscriptSource`,
`CategoryProjection`, `TranscriptPageBuffer`, `TranscriptHistory.prepare_scroll`
and `TranscriptBodyPreparation.prepare_fragments`.

This is the IMPL-4 ownership case: an existing implementation owns the operation
and its callers consume it. Lexical census does not establish dynamic external
aliases or overrides, runtime equivalence, installed UI behavior or duration.

## Remaining qualification

The existing `transcript_prefetch_pilot.projected_checks` now covers both
raw/upstream branches, selected and empty projected intervals, bounded raw
transport rounds, and source/demand revocation during actual category
projection. Its held projection resumes the original category worker; the
control creates no alternate source or projection answer. Original buffers and
runtime workers are closed in the control's finalizers.

`owner-after.json` records complete288/394/41/249 module coverage with zero
omissions. The owning source has one projection invocation and four consumers:
boundary, foreground, upstream prefetch and raw prefetch.

One bounded source-control attempt under the system interpreter imported the
retained Core and Textual wheels directly, with no installed-holder access.
It stopped during Core import: `NativePackageError: Installed native package
resources are unavailable`. Core's original import requires filesystem-backed
packaged resources; importing its ZIP alone cannot supply that installed
contract. No control assertion or native process ran. The original exit1,
traceback and exact operands are retained in `source-controls.*`. No resource
override or retry was made.

The authored controls remain unexecuted pending an eligible named package/import
purpose. No broad old App, movie, build or provider repeat is part of this
checkpoint. Runtime qualification and installed UI behavior remain open. Full
runway and continuous workflow performance also remain unfinished.

## Actual merged442 integration and continuous control closure

This successor now normally contains actual merged442 maincb9bd5c89. The
qualified442 source/control/29-check App remains frozen on b791; no replay,
build or holder purpose is inferred by this source join.

The original continuous adaptive-reader control imposed a single-viewport
forecast ceiling and waited for zero idle runway. DirectionalPreparation
already owns a velocity/delivery/destination prediction; StationaryPreparation
owns settled demand and PresentationBudget owns a retained idle reserve.
PreparationRuntime bounds actual prepared entries/bytes and in-flight work.
The control now waits for that original stationary demand and reads the
declared baseline/resource bounds. Fast-vs-slow/reversal/End/native bounds,
unchanged idle misses/provider requests and draft/Undo/read-position assertions
remain. No production timer/flag/guard, alternate predictor or new harness was
created. viewport_runway_pilot's one-viewport assertion is retained because
that case deliberately sets the original user configuration to one.

All288production/394tests/41tools parse through the existing Package with
zero omissions; original249 native context unchanged. Neither this control
correction nor the prior ZIP import refusal proves configured continuous UI
acceptance. The authored localhost saved-state reply and the configured
real-retained source fixture remain distinct scopes. No App/import/provider/
native run, package mutation, SDK input or physical recording was started.

## Prepared affected installed control

The existing prefetch pilot has a targeted --projected-only mode. It checks the
installed distribution path before its new projection component cases, then
borrows the original transcript_history_pilot App/private Comms registry and
original native-format journal with alternating user/assistant records. Actual
category selection drives the original filter, projected pager and lookahead.
The observer executes original prefetch and body-preparation operations; it
records incoming body dispatch only after that instance's original dispatcher
returns. A revoked preparation that returns without dispatch earns no credit.

This is an authored installed App control, not configured-provider or physical
motion proof. Raw mixed-category intervals, selected assistant body dispatch,
source retirement and runtime bounds are asserted. The unchanged original App
context owns shutdown. The prior broad navigation body has identical AST under
its new non-targeted branch, as recorded in projected-app-control-source.json.
Temporary fixture output is removed by its original lifetime. No new harness,
production change, execution, build or holder access occurred. Future purpose
must bind the exact controls and installed source, then join owned children and
restore the actual floor.
