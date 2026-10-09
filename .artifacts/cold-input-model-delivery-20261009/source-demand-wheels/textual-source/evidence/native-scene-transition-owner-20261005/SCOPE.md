# Use the original scene and size owners for frame transitions

Base: merged native70 c5e7eba344bd2982f30338e8acd18210e19de2ac.
Same completed native checkout; Text70/68/69 source proofs and wheels retained.

Source finding: reflow_visible substitutes an empty predecessor when the last
committed scene is a full map. Its damage comparison then treats the root and
unchanged chrome as new. Full reflow after scrolling also uses the old full map
for damage instead of the latest viewport scene. These are source-supported
wrong predecessor choices, not attribution of the original RichVisual sample
or a measured CPU/FPS improvement.

Compositor owns the existing published scene map. Make that acquisition carry
reflow, visible reflow, lazy full geometry publication and layer projection;
delete their independent predecessor choices. Keep logical show/hide membership
and conservative viewport exposure separate: a complete geometry query does
not prove that every widget has consumed native size publication. Capture
geometry and current-placement validity retain their existing contracts.

Widget._size_updated already owns size, virtual extent and container changes
and explicitly returns whether a Resize event should be sent. Screen must use
that result instead of the parallel region-size-only ReflowResult.resized set.
Delete the set, field, comparison and every consumer. ScrollView keeps its
independently authored virtual extent and container projection but reuses the
existing Widget size commit; its original scrollbar resource retirement stays
with its existing scrollbar update behavior. No change to the size-hook ABI or
Toad Body/Window callbacks.

AST and complete declaration/caller/lifetime reading precede edits. Preserve
native show/hide order, viewport geometry targets, stable paint ties, authored
scroll extents, scrollbar feedback, capture and lazy-layout semantics. No new
map/cache/type/state flag, caller-built readiness predicate or alternate paint
path. Native Compositor/Screen/ScrollView only; no Toad writes.

Batch source and affected native App checks after the coherent implementation.
Existing Heisenberg workflow owns the next meaningful changed installed frame
and motion qualification; no repeat of native70/68/69 controls, provider,
recording, environment, installed package or native SDK build. Source-only
until those boundaries are qualified. CI is deferred; results are recorded
without adding a delivery wait.
