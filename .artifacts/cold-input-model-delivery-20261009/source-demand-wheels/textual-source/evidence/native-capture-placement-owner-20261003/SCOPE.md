# Use the original capture placement for native geometry queries

Extend existing Compositor geometry acquisition; no new type, map, cache, flag,
scene, environment or recording. Parent granted `_get_geometry`/`get_offset`;
Heisenberg owns the independent Toad body/writer family and its physical recorder.
Reuse this checkout after normal main integration; keep scoped44 frozen.

Existing capture geometry already declares placements for its admitted members.
`_get_geometry` should consume those placements before constructing an ancestor
list. Only missing queries need the original ancestry relation to refuse an
omitted capture descendant; unrelated queries keep ordinary scene selection.
`get_offset` currently bypasses this behavior and independently chooses visible
or lazy full geometry. Delete that algorithm: offset derives from `find_widget`.
Screen and Widget geometry readers consume the same original placement owner.
Ordinary missing geometry retains lazy arrangement; no capture descendant may
escape to another scene. Nested/failed synchronous captures restore custody.

Read original `_arrange_root`, cover/scrollbar geometry, Intrinsic/Placed resources,
DOM ancestry, Widget region/content/size, StylesCache rendering, Screen public
geometry methods and the Toad capture caller. NRA Package parsed all249 native
and289 Toad production modules with no omissions at the production-equal frozen
source; targeted before/after owner evidence records consumer closure. AST does
not resolve all dynamic overrides or external plugin calls; those retain the
public geometry contract and need semantic reading.

Source reasoning and coherent implementation come first. One final bounded native
batch must detect omitted-child fallback, wrong external-scene selection, offset
bypassing capture, and failure/nesting leakage; use the actual native App. One
later changed installed journey belongs to Heisenberg and joins useful changed
source. No repeat44 tests/film, test-first design, provider call, overlay or new
capture. This removes repeated work and a competing selector, not a measured
CPU share or a smoothness claim.

## Published implementation and consumer closure

Production checkpoint `c95c51a345`: `_compositor.py`8 added /13 deleted lines
against main `db8becffb36294cb4cd9948ad3d891bbdc45a548` (merged44).
`get_offset` no longer selects visible/full scene geometry or catches its own
missing-widget case. It derives the offset from existing `find_widget`.
`_get_geometry` takes a present capture placement directly; only absent members
walk ancestry, and an omitted descendant still raises NoWidget. Other widgets
use the original published/lazy scene. Capture selection/restoration, full_map,
Widget/StylesCache and Screen signatures are unchanged.

All249 native modules parsed after implementation, zero omissions. The complete
289-module Toad dependency evidence is reused unchanged: its existing body
capture still acquires published placements and consumes native strips. There
is one capture custody declaration/context owner and one placement selector;
Screen.get_offset and Widget region/content/size readers derive that selection.
The public offset reader adds one `find_widget` call; site counts are not a debt
or speed score. Dynamic property/plugin dispatch remains outside AST proof.
The unrelated compositor widget-membership query retains its distinct meaning.

## Final bounded native qualification

Only the changed contract was exercised; the8 accepted44 cases were not rerun:

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 timeout 45s python -m pytest -q -p no:cacheprovider tests/test_compositor_frame_damage.py::test_capture_geometry_and_offsets_share_original_scene_custody
```

The original native App reported **1 passed in0.61s**. It arranges a real visible
scene and a complete body from the native published placement. An offscreen
capture member has geometry and offset without forcing full_map. A hidden,
omitted descendant is refused by both public readers. An unrelated widget keeps
its current scene. A failed nested context restores the outer original resource;
after capture ends, ordinary offscreen lookup may still arrange full geometry.
No fake UI, scene map, protocol or replacement application was supplied.
The log-reader shell exited0; pytest's exit status was not logged separately, so
no separate process-exit attestation is claimed. No repeat solely for that gap.

The resource check reported home7.9GiB/root7.3/RAM11.1/swap11.9 pressure. This
subsecond in-process native case reused system Python/dependencies, no cache,
parallel fixtures, helpers or environment allocation. No provider/film/export.

This is a source-qualified working checkpoint, still draft. A changed installed
saved-UI journey must join Heisenberg's next useful batch; completed402/44 cannot
qualify changed45. No measured CPU gain or smoothness claim; original production
performance scope remains open. Protected artifacts and prior negative evidence
remain untouched.
