# Style and geometry source checkpoint

Production source: `95d3b99b8287af866290bc5398c869325d2d2913`, normally
integrated with main `69954eb38` (Text38). Nine production files: **222 added,
79 deleted**. This is a source checkpoint, awaiting the single paired installed
journey with Heisenberg's Toad384. Current default installations are untouched.

## What owns the work

- `Styles._update_rules` owns original rule membership, value mutation, update
  epoch and descriptor publication. Set/clear/reset/merge/compiled replacements
  all use it. Stored CSS `initial` (`None`) is preserved separately from removal.
  Descriptor lookup and geometry classification happen before mutation.
- `StyleProperty.affects_geometry` owns rule effects through the existing
  descriptor family. Color, opacity, hatch and transition changes retain paint
  validity without automatically destroying native Content geometry. Unknown
  descriptors and StringEnums remain conservative: native Content measurement
  reads wrapping/overflow even when the descriptor schedules only repaint.
- The original `_geometry_revision` declaration now lives on the common DOM
  ancestor, replacing Widget's declaration. Existing style publication now
  retires source-subtree measurement resources once, including original virtual
  children, and aggregates the result into the ancestor publication. The old
  recursive Flow sensitivity query is deleted: it could discover an opaque
  child's sensitivity without retiring that child's actual cached resources.
  Native ancestors do not rescan siblings. Unknown custom measurements and
  layout hooks remain sensitive even when independent of available height.
  No cache, registry, second counter or retained policy flag was added.
- Widget arrangement/box/height proofs and `SubtreeGeometryKey` consume that
  original geometry resource. A box key reads its parent's actual auto-width
  and auto-height inputs, not unrelated changes in the parent's whole subtree.
- The existing Static rendering hook narrows only original Static.render,
  original visual getter and an already-retained original Content visual.
  Unknown/custom/unmaterialized visuals stay conservative; classification
  does not invoke render or create a visual. Flow/Grid/Stream share the original
  local source-sensitivity operation while preserving their distinct box
  algorithms. Only original native pre_layout/process_layout hooks narrow
  style inputs; declaring incoming-height independence alone does not.
- The global Styles paint epoch and DOM subtree paint epoch are retained.
  Toad RetainedPaint/PaintState consumers are unchanged: geometry validity
  does not substitute for pixel validity.
- Heisenberg's contribution makes original MessagePump exit cover startup too.
  Widget closes messages/cancels workers before descendant and asynchronous
  Unmount hooks; the duplicate late Unmount cancellation is deleted. Startup
  cancellation still propagates and the original mounted-event finally remains.

## Replaced work

Deleted five competing Styles write/publication paths, duplicate enum/scrollbar
publication, Widget's duplicate geometry declaration/ancestor walk, geometry
consumers of broad paint-only style keys, and the late worker-cancellation
consumer. Pattern references: IMPL-6, IMPL-12 and IDEN-1. Original external CSS
values, renderer contracts and legitimate different layout operations remain.

`owner-consumers.json` uses the existing NRA/refactor-audit Package parser:
249 native modules and 288 Toad modules, zero parse omissions. Its final-source
entry points at the exact production checkpoint. Removed `_mark_updated` and
`SubtreeGeometryKey.styles_key` have no production/test consumers. The sole
geometry declaration is DOMNode; the sole original rule-write boundary is
Styles._update_rules. AST does not prove dynamic MRO resolution. Custom source
hooks were read semantically; their default remains conservative.

## Checks and limits

One affected sanity batch covers raw rule presence/publication, inherited
paint, native color-only geometry reuse, custom renderer measurement, raw
native display projection, structural/box/subtree reuse, mount/unmount and
worker custody. Exact final source: **140 passed in 6.35 seconds** using existing
system Python, with no new environment. The first **135 passed / 3 failed** log
is retained. It exposed a stored-initial/removal distinction and overly broad
parent-key invalidation; source was corrected without weakening assertions.
The intermediate 138/139 passing results are retained at their actual source
boundary. Source review then completed inherited opaque-child invalidation and
custom layout-hook provenance; the final batch includes both affected paths.

These checks do not prove visible FPS, CPU improvement, complete End behavior
or the installed Toad lifecycle. Heisenberg owns the single changed normal69
pair and real saved-session motion/profile gate. PR355's old source/failed End
movies remain protected; its limited mount/admission closure is not a speed
or final-End claim. No independent recording or provider run was performed.

## Delegated cancellation follow-through

The paired lifecycle pilot reported an awaiting worker as
`WorkerFailed(WorkerCancelled)` during teardown. Its primary held-render timeout
was separately a fixture task-family boundary: Heisenberg corrected the hold to
Markdown tasks and retained the original renderer for sidebar/other tasks. That
timeout does not establish a primary product mount or End failure.

The existing WorkerCancelled declaration now composes WorkerError and
asyncio.CancelledError. Original Worker._run handles the cancelled outcome
through its unchanged asynchronous cancellation algorithm; no tuple classifier
or viewport catch was added. Worker.wait, terminal states and errors retain their
original public contracts. Generic `except Exception` still matches WorkerError;
this is not a blanket claim about every MessagePump cancellation route.

Deleted Worker._cancelled's declaration, write and reader. The existing
cancelled_event owns the request, and is_cancelled derives it. Publish that
request before task cancellation. A request and a terminal CANCELLED outcome are
different facts: an awaiting parent may receive cancellation without anyone
requesting its cancellation. Neither terminal state nor error was copied into
this request signal.

`worker-cancellation-owner.json` records before/after declaration and consumer
AST through the existing Package parser across 249 native/288 Toad modules with
zero omissions. Worker private flag references were all in the original owner;
unrelated Timer fields and unresolved dynamic receiver identities are explicit
limits. Existing public catches remain in their actual lifecycle boundaries.

Only the changed worker family was checked afterward: **59 passed in 2.00s**,
including original real App workers with child cancellation, public wait errors,
terminal state and request/outcome separation. The prior geometry/paint 140-case
result remains at its unchanged source boundary. All logs are retained. No
physical recording has run for this amended source; Heisenberg owns that single
paired installed qualification next.
