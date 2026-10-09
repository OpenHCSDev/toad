# Reuse the original scene acquisition across layout and paint

Native contributor owns `_compositor.py`; Heisenberg415 owns the Toad reader,
viewport and frame consumers. Same checkout, normally integrated main48.
No new environment, compositor, map, cache, type, state flag or recording.

Read the original412 saved-session profile and original native lifecycle first.
It records `layers` during held Up and `_get_renders`/`render_regions` during
motion. Those are observed stack transitions, not calls, durations or CPU share.
Raw evidence stays at
`/home/ts/.cache/agent-scratch/body412-materialization-public-20261003-01/capture`.

The source supplies the concrete repeated work: Screen's size-publication pass
acquires `Compositor.layers`, sorting its original committed geometry. Paint
then acquires `visible_widgets`, independently sorting that same geometry in
`_paint_regions`. The existing ordered layer resource must carry the work for
visible clipping, hit testing, cuts and screen paint. Body capture orders its
own synchronous geometry through the same original ordering algorithm, without
publishing it as screen geometry or retaining another map.

Close full/partial/inline/export/subtree paint consumers together. Remove the
extra eager scene snapshot in `_get_renders` where the supplied paint mapping
already owns this synchronous cohort, and lend the same cuts resource through
partial composition and its update. Preserve native layer order, clipping,
exposure, source/style metadata, crop semantics, capture isolation and lazy
public geometry lookup. Keep ordinary widget lifecycle callbacks unchanged.
Patterns: IMPL-12/13, duplicated acquisition rather than new source authority.

Before evidence uses the existing NRA/refactor-audit Package parser over complete
native249 and Toad288 modules, zero parse omissions. AST establishes declared
consumers; dynamic extensions and arbitrary mutation of private compositor
resources cannot be resolved statically. Read the resulting sites semantically.

Implementation first. One final bounded native control batch must protect actual
layered/occluded/wide-row output, clipping, partial/full/export/capture and input
geometry. The next meaningful changed Heisenberg installed saved-session journey
supplies physical qualification. No unchanged412/48 repetition, provider call or
isolated speed claim. Full144Hz/CPU/IRC/DM/cold-warm performance remains active.


## Working checkpoint and final native batch

Production `b2ea6c596f05b5c7d6da70f71045bee40b605437`: `_compositor.py`
24 added /35 deleted. The original cached `layers` orders the committed scene;
`visible_widgets` now filters that same ordered resource. `_ordered_geometry`
is the sole ordering algorithm, used by the original screen lifetime and the
separate synchronous subtree-capture lifetime. No additional scene or cache is
retained. Full/partial/inline/export paint, cuts and hit-testing derive the same
original filtered cohort. `_get_renders` borrows its mapping directly, removing
both eager whole-cohort list branches. Partial output retains the exact cuts it
consumed instead of reacquiring that resource after rendering.

The existing native full-render comparison observers in two test files were
migrated to the actual keyword-only `widgets` contract; they call the original
renderer with the same original cohort. No synthetic geometry, Strip, protocol,
backend or substituted renderer answers were added.

Before/after Package evidence covers native249 and Toad288 production modules,
zero omissions. The ordered screen/body algorithm is declared once; its two
consumers select genuinely distinct original geometries. Existing scene
invalidation still retires `layers`, visible regions, cuts and hit-test rows;
Screen's size/lifecycle callbacks and ordinary lazy geometry remain unchanged.
External dynamic plugin/private-resource mutation is outside AST proof.

One final native batch: **14 passed in1.31s, exit0**, in
`native-sanity.log`/`.exit`. It exercises actual native Apps and layered widgets:

- inherited/custom layer order protects original paint priority;
- covered/partly covered output and horizontal wide-cell clipping protect
  exposed content and preserve native full-render output;
- three sparse damaged-row cases protect partial repaint selection;
- original caption damage after lazy full geometry protects the old and new rows;
- nonzero body capture and capture-scope geometry protect detached row coordinates
  and prevent capture from replacing the original published screen.

Implementation and the working source were pushed before this single batch.
Only existing Python/dependencies were used; no environment, recording, provider,
worker pool or installed prefix was started or changed. Resource warnings were
right-sized to this one bounded1.31s process. No unchanged48/412 check repeated.

Source-qualified draft; changed installed qualification joins Heisenberg415's
next meaningful saved-session UI journey. No performance, smoothness or FPS
claim from deletion counts or the14 native controls. Full performance remains
active.
