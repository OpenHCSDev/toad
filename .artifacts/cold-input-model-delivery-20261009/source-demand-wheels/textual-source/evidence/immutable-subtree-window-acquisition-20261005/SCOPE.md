# Immutable subtree window acquisition

Base: published frozen combined Text63/64 08e3dd6b3c7839baafcac6ff9ea61eb510ff9573.
The qualified source controls and 487b standalone wheel remain unchanged.

The existing immutable SubtreeGeometry owns source placement, membership, clip
scope and source order. Its viewport projection still scans every stored entry
before rejecting offscreen rectangles; restore also flattens complete native
membership on each use. Preserve complete capture, full-map queries, explicit
reader paths, overlay/screen-dependent fallback and bounded resource retirement.

Reuse the existing native spatial acquisition mechanism only as a derived index
of the original immutable resource, not a second scene or mutable geometry
registry. Migrate Placed and Intrinsic capture/publication together. Investigate
membership consumers before changing the published considered-widget contract.

Claim: native _compositor.py subtree capture/projection/restore and necessary
original membership consumers. No Toad, installed prefix, SDK, keeper, App or
recording lease. Heis owns the Toad workflow and original453 qualification.

Source ownership reasoning and implementation precede the final proportional
native App source controls. No CPU, frame latency or smoothness claim follows
from source deletion or a spatial-query operation count.

## Frozen implementation and source qualification

Production source: 0ab59a0466cff6fd2bd8c3747b1be7e2fd660586 (native product
byte-equal to the actual 5a569464 source batch). One production file: 33 added,
6 deleted lines compared with frozen08e3; no other native production changes.

`SubtreeGeometry.capture` now binds the original source ordinal alongside each
entry in its one immutable geometry mapping. Placed capture and Intrinsic capture
both consume this shared algorithm. Its private cached spatial resource uses
EXISTING SpatialMap and contains widget/ordinal references derived only from that
mapping. No second geometry map, ordinal registry, mutable update path or extra
lifetime owner was introduced. The original cache capacity, source key and
retirement own the index's lifetime.

Viewport publication queries that resource in original source coordinates, adds
root/explicit retained paths by direct lookup, and projects candidates in original
insertion order. This replaces the every-entry viewport scan. Complete full-map
and body capture consume all original entries and do not require the spatial
index. Screen-dependent/overlay clips still select Placed geometry at capture;
the index uses those actual absolute rectangles, not layout's fixed/overlay flags.
Exact region and clip admission remains unchanged after the candidate query.

Retirement now uses original geometry-key and membership-set disjointness rather
than allocating an expanded tuple of every referenced widget. Complete widget and
invisible-widget membership remain their original immutable sets, and restore
still unions them: this O(n) work is a required current contract, not claimed gone.
Index construction is source-size/extent work once per retained resource; coarse
spatial candidates still require exact clipping. No asymptotic/time claim applies
to the complete rendering workflow.

One final native App/source batch yielded 32 PASS and one failed NEW overlay
expectation. The original log and negative receipt are retained. Its expected set
used an empty intersection rectangle as painted (row9 y10 outside a ten-row
viewport); original Region.overlaps can return true for that zero-height shape.
The control now consumes the existing Compositor._paint_regions owner plus the
original explicit target. Only that changed control was re-run: PASS, 0.35s
pytest / 1.49s controller. Native production is byte-equal across both receipts;
the other 32 accepted controls were not repeated. No Region behavior was patched
or timeout/geometry oracle relaxed. SANITY.json binds these exact limits.

Actual source-App coverage: 240-row cached body forward/reverse acquisition,
offscreen explicit reader target, complete capture/full-map lookup, considered
membership, authored display invalidation, cache-budget/retirement; fixed child
and screen-overlay fallback/order against the original uncached scene; existing
native paint/layer/point-hit/damage and SpatialMap controls.

After: native249/tests460/Toad288 parsed without omissions. Before/after complete
root candidate output is in owner-consumers.json; dynamic aliases and external
subclass resolution remain explicit limits. Pattern IMPL-12: original shared
capture/publication behavior replaces the duplicated source-enumeration path.

No new env, build, keeper, installed prefix, Toad App, provider, physical recording
or CPU/smoothness qualification. Draft source checkpoint; affected installed
qualification belongs to a future meaningful Heis integration purpose. Frozen
Text63/64 08e3/wheel487 and Heis453 operands remain untouched.
