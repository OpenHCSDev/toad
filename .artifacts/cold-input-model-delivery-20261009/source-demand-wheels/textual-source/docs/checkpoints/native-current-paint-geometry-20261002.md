# Current native geometry for body capture

Scope: reuse Compositor's original geometry selection in find_widget and
can_render_subtree. Heisenberg owns the Toad viewport, layout targets and full
application integration. No second scene, geometry cache or body implementation.

The original E03 profile contains this held-scroll path:
retire_native_body -> can_render_subtree -> full_map -> _arrange_root.
Admission currently forces the full scene even though find_widget already accepts
current visible geometry. The fix preserves its selection order and NoWidget
boundary, and gives admission the same original lookup.

Existing NRA Package source mapping parsed all 249 Textual modules with no
omissions. Consumers include Screen, Widget geometry properties, selection and
render_subtree_strips. Their public geometry contracts remain unchanged.

E03 kernel whole-phase CPU was 91.16% and 69.89% during the two held-Up phases,
and 39.27% and 32.65% during the longer midhistory phases. These include settling
and diagnostic work; stack observations do not attribute those percentages.
Late stationary observations mainly select backend read/attestation work, not
whole-tree style/layout. That source finding was handed to Arendt.

Implement the native owner change first, then run one source-native geometry/body
sanity batch and the sole changed installed journey owned by Heisenberg. E03
remains the baseline; no provider input or duplicate recording is needed.

## Published owner change and final sanity

Production change: `_compositor.py`, 22 added / 18 deleted lines. `_get_geometry`
is the sole selection algorithm used by both `find_widget` and
`can_render_subtree`. `render_subtree_strips` retains original current geometry
and native renderer; Screen/Widget/selection consumers keep their public API.
No new geometry state, scene or cache. Current viewport geometry is selected
before a lazy full arrangement; invalidated full geometry cannot win.

The existing native target checks passed for admission without full arrangement
across four widths/scroll positions and refusal of removed/foreign bodies.
The existing real Toad retained-body family passed source updates, styles,
resize, three body kinds, warm admission, stationary resource retention,
native input and disposal. Both used the changed Textual source with the
existing E03 dependency interpreter. That interpreter lacks pytest; the
unchanged async native App test functions were called directly.

Receipts are in `native-current-paint-geometry-24-source-receipt.json`.
The preceding source checks alone did not qualify an installed application or
performance result. Heisenberg owns combined integration and layout targets.

## READY: joined changed installed journey

The same installed Toad319/Textual24 run completed in 106.153s with all seven
native input checks, unchanged original owner epoch/runtime and clean process
cleanup. Directly viewed held-Up, stationary and final End PNGs retain readable
body and chrome. Final End has current extent and ready retained resources.
The immutable installed receipt is
`native-current-paint-geometry-24-installed-receipt.json`.

This qualifies the geometry change as a useful checkpoint. Motion is still
sparse/discrete. The 78.88% marked-Up CPU versus E03's 91.16% is not a controlled
causal result: intervals, source workload, Core pin and export costs differ;
Up writer p95 worsened. The profile has one reported sampling error.

The same original ProfileTrace identifies two remaining full-layout callers:
retirement before viewport layout supplies a newly mounted root's geometry,
and descendant region queries during native subtree strip rendering. These
were handed directly to Heisenberg for the full performance continuation.
No second capture, package or provider operation was started.
