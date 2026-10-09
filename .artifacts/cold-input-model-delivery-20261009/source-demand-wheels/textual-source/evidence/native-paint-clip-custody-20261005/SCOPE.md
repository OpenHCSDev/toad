# Native paint rectangle custody

Base: actual Textual main06771827eeff2a98c40a41fd2bc6cb6313db7a87.
Merged65 source, e253 wheel and all controls remain untouched.

The existing compositor paint mapping derives ordered widget paint from original
MapGeometry. It currently stores an unbounded clip and each cuts/render/chops
consumer re-intersects the same original region. Make `_paint_regions` own the
positive rectangle within original scene/capture bounds, then consumers borrow
that fact. Damage crop and foreground exposure are distinct later selections.
Raw MapGeometry, source order, geometry lookup, membership and retirement remain
their original owners. Existing layers are already cached per published scene;
complete widget membership remains necessary and is not removed.

Claims: `_paint_regions`, `_cuts_for_regions`, `_get_renders`, `_render_chops` and
related compositor paint-query consumers. No new type, field, map, flag, cache,
timer or alternate scene. Heis owns Toad body/frame consumers. Native source App qualified below; no installed package, provider, recording
or gain qualification.

Complete roots and consumer evidence precede changes. Source semantics first,
coherent caller migration, then proportionate validation under an actual later
grant. Pattern IMPL-12: repeated geometry acquisition by related consumers.

## Published coherent source

Production7934c06e0cbb03aa4e10fb53bc1a09f088f49e73: one production file,
16 added /23 deleted lines relative to actual main06771827. Native source
App controls qualified below; installed Toad/frame/performance not qualified.

The first pair member stays the ORIGINAL widget region, including its origin and
logical dimensions. The second is the positive original region/clip intersection
within this screen or detached capture's bounds. Only this existing paint mapping
owns that admitted rectangle. MapGeometry itself and all considered/invisible
membership remain unchanged, including offscreen explicit geometry and full-map
or complete body capture.

Cuts trust this already bounded rectangle rather than intersecting region, clip
and bounds again. Widget rendering keeps the distinct vertical damaged-row crop
and foreground-exposure selection. It emits the actual selected rectangle plus
strips; the only native unpack consumer now borrows that rectangle directly. The
unused original-region return and the repeated chop intersection are deleted.
Original widget origin is still used to request relative render_lines, preserving
metadata/selection/link coordinate semantics. Partial horizontal damage retains
original cut alignment; no dirty-x clipping or renderer policy is added.

Existing layer sorting is already cached per published scene, so it stays. The
unbounded geometric clip is still available from original MapGeometry to geometry
consumers. Positive-pixel paint membership is distinct from complete native widget
membership; empty intersections cannot paint and remain available to logical
geometry/lifetime consumers through their original owners.

Complete native249/tests460 and Toad288/tests397/tools41 roots parsed without
omissions before. After native249/tests460 parsed without omissions. All actual
native cut/render/chop producers and callers were migrated; wrappers in existing
controls only delegate to the original renderer and do not unpack its old triple.
No obsolete triple annotation/unpack/reintersection remains in the owned roots.
The original graph and after acquisitions are in owner-consumers.json; dynamic
aliases/external private-method overrides remain explicit limitations.

Heis confirmed no known Toad reader requires the paint pair's unbounded clip.
Pager edge readers borrow the unchanged original region, not paint extent. His
pixel/window consumers keep their genuine Window clipping fact; once normally
paired with this library, their extra region intersection can be reviewed as an
identity operation. No such caller migration is made against old native65 or the
current installed prefix, and no compatibility/version branch is introduced.

At the original2e8e source checkpoint, no source App/control run, wheel,
package access, keeper, provider, capture or frame/CPU measurement was performed. Final affected controls remain to exercise
partial horizontal/vertical damage, offscreen-origin body capture, overlays,
selection/link metadata and native interaction/retirement under the next actual
grant. Frozen65/e253/controls and Heis453 tuple remain immutable.


## Scoped source qualification

Source/control7e0ad94ca9f19506f9a1ed2b8bb2f2e3bd939569; production remains
7934c06e0cbb03aa4e10fb53bc1a09f088f49e73. ONE affected native source App batch:
22PASS/2.54s pytest,3.745s controller, exit0. System /usr/bin/python with existing
dependencies and PYTHONPATH=src; no new environment/build/installed prefix access.
Exact command, log and SHA are source-batch01.json/source-batch01.log.

The existing point-hit scene checks original extent/origin vs bounded positive
paint, negative origins, fully clipped logical membership, hide/move/remove and
original raw clip. Existing capture controls check nonzero and negative original
bounds, cuts and full row content, original maps/offsets, hidden descendant refusal
and renderer-error resource release. Existing damage/exposure controls check
sparse vertical rows, dirty-x cut alignment, overlap exclusion and terminal parity.
The horizontal exposure case additionally checks authored link/click metadata;
existing wide-cell and native selection controls preserve selected pixels and
metadata. Pending actual Unmount controls ensure paint projection retirement
cannot retain old geometry/cover or revive pointer/selection resources.

These controls confirm native source behavior for this family. They do not prove
installed Toad pairing, Linux terminal frame timing, cold/warm motion, CPU gain,
144Hz or full performance. Frozen65/e253 and original negatives remain unchanged.
Future changed installed integration belongs to Heis; no current holder purpose
or native66 wheel is implied. No further accepted-source repeat requested.
