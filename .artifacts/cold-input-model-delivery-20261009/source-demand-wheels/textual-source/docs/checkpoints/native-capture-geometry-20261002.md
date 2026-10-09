# Native geometry during retained strip capture

Continue merged Textual24 using the existing Compositor capture and geometry
owners. Heisenberg grants render_subtree_strips, renderer geometry consumers,
StylesCache and Widget geometry within capture. He owns early registration,
viewport/layout timing and the Toad integration.

The original installed319/Text24 profile records:
render_subtree_strips -> _render_chops -> _get_renders -> StylesCache.render_widget
-> Widget.region -> find_widget -> _get_geometry -> full_map -> _arrange_root.
The strip renderer already has the body's complete native arrangement, but
descendant geometry queries independently select the screen-wide map.

Make the existing native geometry owner select the original arrangement used
by the active capture. Preserve absolute screen-coordinate Widget geometry,
original strip coordinates, invalidation and nested/failed capture lifetimes.
Reuse the existing arrangement resource; no second map, store, fake Screen,
copied widths, renderer or geometry cache. Migrate the complete shared lookup
family rather than special-casing StylesCache.

Read existing geometry/projection/lifetime owners and AST consumers first;
implement the coherent family and delete replaced decisions. Validate once at
the end using the existing native body family. Heisenberg owns the later changed
installed recording; no new environment, provider input or duplicate capture.

Ready checkpoint24 remains qualified and unchanged. Remaining discrete motion,
full-layout work and overall CPU targets are not closed by that checkpoint.

## Working source checkpoint

Compositor owns the complete native capture arrangement at the original absolute
root placement. The existing cuts/chops algorithm now takes original Region
bounds for both screen and body rendering. Its scoped geometry resource holds
references to that same map/root; all descendant Widget/StylesCache queries
select it through the one `_get_geometry` owner. Published maps are not swapped,
and the scope releases on nested completion or renderer failure.

The first native check preserved a real negative: the selected offscreen row
had a78x2 box but an empty0x0 Widget render cache. `Widget.render_line` now
validates its existing cached render size; `_render_content` stamps the exact
size it rendered. StylesCache validates its complete original render size,
replacing the insufficient width-only stamp. No copied content or new cache.

Production: three files,76 added/36 deleted lines. Every native cuts/chops caller
uses its owning Region bounds; Widget and StylesCache public consumers remain
on the original geometry lookup. NRA parsed249 modules with zero omissions;
AST receiver ambiguity is retained rather than claimed as dynamic proof.

The real native offscreen-descendant check passes actual text, absolute screen
coordinates, dimensions, no whole-scene rebuild, unchanged published maps and
failed-renderer cleanup. The joined original Toad body-family check passes all
three body kinds, geometry targets, style/resize updates, retained reentry,
native input and disposal. See `native-capture-geometry25-source-receipt.json`.

This is a useful source checkpoint, not an installed performance result.
Heisenberg owns the one later changed installed journey and early layout timing.

## READY: same changed installed322/25 journey

The joined installed public saved-history gate completed107.353s with all seven
input assertions, original owner/runtime unchanged and clean process cleanup.
Directly reviewed held-Up/idle/final End PNGs remain readable; final native
extent is105/105 with all bodies ready and preparation settled. The exact
same-run receipt is `native-capture-geometry25-installed-receipt.json`.

Original ProfileTrace reports1474 samples/zero errors. No descendant strip
capture→fullscene chain was observed; source ownership and native checks close
that family. This is not proof of absence for all sampling intervals or a CPU
attribution. Retirement admission still has23 observed fullscene stack groups.
The scroll fastpath drops declared geometrytargets, a separate original caller
closure handed to Heisenberg for follow-up.

Busy motion remains sparse/discrete. Up writer median/p95 is30.31/166.68ms;
reverse31.31/242.57ms has worse p95 than the preceding gate. MarkedUp78.86%CPU
and idle29–37% remain substantial, and intervals/Core/workload differ. No smooth
scrolling,50ms,144Hz,overall CPU or default-live claim. No repeated capture.
