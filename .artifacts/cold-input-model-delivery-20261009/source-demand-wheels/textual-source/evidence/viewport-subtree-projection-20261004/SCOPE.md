# Complete resources and viewport geometry

The existing `SubtreeGeometry` resource owns complete reusable arrangements.
Its viewport consumer currently publishes every cached descendant before the
compositor sorts and clips that scene. A long live body therefore projects its
offscreen descendants on each scroll even when only a few rows are exposed.

This change makes the original geometry family own viewport projection for
both restored and newly captured resources. Complete capture, ordinary lazy
full-map queries, explicit reader and interaction targets, overlays, covers and
scrollbars retain their original contracts. No second geometry map, cache or
state owner is introduced. Heisenberg confirmed the Toad contract: body roots
and explicit anchor paths need publication; body capture separately acquires
complete geometry. He owns the affected installed qualification.

`SubtreeGeometry.project_into` now owns both cheap source-bounds rejection before
clip/rank/placement transformation and exact clipped publication. Placed and
intrinsic resources implement only their original coordinate transforms. The
cache-hit and fresh-capture publication algorithms are replaced by one call;
enclosing complete captures keep complete descendant resources. Generic
`find_widget`/`full_map` and full subtree captures remain complete.

The one final native batch passed 26 controls in 4.25 seconds using existing
system dependencies. The added actual native App case exercises forward and
reverse scrolling, complete body capture, an offscreen reader target, lazy full
geometry and authored display invalidation. Existing controls cover viewport
targets, scene ordering, clipping, cache retirement and source mutation. See
`SANITY.json` and `owner-consumers.json`; both native source snapshots parse all
249 production modules without omissions, and the Toad context parses 288.

Complete cached membership is still retained and every resource entry is still
visited. The change removes unnecessary offscreen transforms and downstream
scene publication/sorting; it does not establish CPU dominance or frame-time
gain. The affected installed application remains unqualified. This draft has
no build, installed-package, provider or recording purpose.

The separate callback arity source defect remains independent; it does not hold
this geometry change or imply a frame-time attribution.
