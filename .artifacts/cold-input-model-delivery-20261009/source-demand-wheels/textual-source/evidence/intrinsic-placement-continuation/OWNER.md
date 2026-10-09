# Existing native placement resource continuation

Heisenberg owns the existing native compositor family under Toad284/275 whole viewport integration. Base actual Textual main5fbf5c76. Original18 source and evidence are frozen. No new classes, fields, caches, renderer, clock, semantic state or format compatibility.

## Semantic source relation

SubtreeGeometryKey is the existing fourteen-input native arrangement contract. Its intrinsic form previously normalized screen region and clipping but retained outer document virtual offset and absolute paint prefix/rank. Pure prepend, eviction or host relocation therefore rejected a valid body arrangement. Ignoring these dimensions alone would be wrong: MapGeometry carries the root's parent-relative virtual placement and every descendant's native paint rank.

Extend this existing key's intrinsic normalization and project_order. The existing SubtreeMapGeometry projects native region, clip, order and root virtual_region together. The original compositor dictionary key remains root identity: the sole restore caller passes its current native render widget transiently, never stores another owner field. IntrinsicSubtreeGeometry consumes that identity; PlacedSubtreeGeometry retains exact-coordinate matching and culling. Inherited layers, dimensions, style/custody revisions, coverage, scroll offset, screen dependencies, capacity and selective retirement remain unchanged. Screen-constrained/overlay geometry still uses its existing exact placement policy.

Original paint prefix identifies the subtree; only its descendant suffix receives the root's current rank delta. Child virtual regions remain relative to their original internal containers; the root receives current parent-relative virtual placement. An unchanged projected MapGeometry retains native object identity.

Complete source search before implementation: one declaration per key/resource type; one native restore producer and all three projection consumers migrated. No deprecated API/alias/fallback or outside switch. Patterns IDEN-1/IMPL-13/TIME-9. A new placement still uses Widget/layout's existing declarations, requiring no cache roster edit.

```text
src/textual/_compositor.py:65:class SubtreeGeometryKey(NamedTuple):
src/textual/_compositor.py:88:    def project_order(self, order: tuple, destination: SubtreeGeometryKey) -> tuple:
src/textual/_compositor.py:150:class SubtreeMapGeometry(NamedTuple):
src/textual/_compositor.py:174:            order=original.project_order(self.geometry.order, current),
src/textual/_compositor.py:185:class SubtreeGeometry(ABC, Generic[GeometryEntry]):
src/textual/_compositor.py:205:    def restore_into(
src/textual/_compositor.py:210:        self.project_into(geometry, key, clip, clips, root)
src/textual/_compositor.py:215:    def project_into(self, geometry: CompositorMap, key: SubtreeGeometryKey,
src/textual/_compositor.py:224:class PlacedSubtreeGeometry(SubtreeGeometry[MapGeometry]):
src/textual/_compositor.py:230:    def project_into(self, geometry: CompositorMap, key: SubtreeGeometryKey,
src/textual/_compositor.py:237:class IntrinsicSubtreeGeometry(SubtreeGeometry[SubtreeMapGeometry]):
src/textual/_compositor.py:257:    def project_into(self, geometry: CompositorMap, key: SubtreeGeometryKey,
src/textual/_compositor.py:260:            geometry[node], clips[node] = entry.project(self.key, key, clip, root=node is root)
src/textual/_compositor.py:1090:                cached.restore_into(map, widgets, invisible_widgets, key, clip, clips, widget._render_widget)
```

## Final validation boundary

Code reasoning and the coherent implementation precede final validation. Reuse existing native scroll/scene/custody control with prepend/reorder/eviction and complete-versus-culled scene equality, then one meaningful normal installed saved-history physical/CPU gate at a package checkpoint. No source or installed speed claim yet. Source profile evidence motivates this scope but does not assign a CPU fraction. Runtime lifecycle Arendt, compaction/T5 Sch,493 borrowed-reader methods retain their existing owners.

## Source/native final validation

The existing continuous native scroll control now includes prepend, sibling reorder/retirement and host relocation. All15 scene relations match a full uncached native traversal, including native paint order and parent-relative virtual_region. All5 placement transitions retain the same body resource and execute zero actual body layouts. Prepend/reorder/retirement also make zero body.arrange calls. Host offset changes call body.arrange once through native get_content_height, whose existing arrangement cache returns without executing body layout. The first validation incorrectly equated this cached measurement lookup with layout execution; preserve its failed log, then classify the caller rather than suppressing the lookup. The final observer records both lookup callers and actual layout execution.

Original PageDown still performs zero body arrangement calls. Resize/content changes replace the resource; nested scrolling, fixed children, complete-versus-culled coverage and screen/overlay placement still match native uncached geometry. The unchanged projection returns the original MapGeometry before allocating a replacement. Source validation uses the existing installed dependency interpreter but imports this exact worktree's Textual source. It does not establish installed Toad performance or terminal Strip retention. Required next gate is the declared compatible normal installed pair after the parent's493/474 source union, without reusing obsolete native pins.

Evidence: native-scroll-placement02.json and both native-scroll-placement.log/native-scroll-placement02.log. No provider calls or public root/owner/native input were involved.

## Construct each admitted native subtree once

The same add_widget producer copied the complete preceding frame map plus two membership sets at every cache miss, then traversed that complete map again to subtract preceding widgets. A newly admitted body's construction cost therefore grew with unrelated already-built bodies. It now constructs the original map/membership sets for that subtree directly, seals them through existing SubtreeGeometry.capture, and publishes into its enclosing original scene. Nested captures use the same construction path; finally restores the enclosing traversal if arrangement raises. Original global clips/coordinate declarations and bounded selective retirement remain the existing authorities. No new collector, store, family, field or renderer.

Final native-scroll-capture03 keeps all15 scene checks and5 placement transitions. The focused native compositor/visibility/damage batch passes16 checks in1.10s. The original installed efe905 compositor is byte-identical to merged5fbf5c76 (SHA25642df01096d0fb720bcb90589db6979145202e2b3240295b899020fc70e9d2ac2): the identical extended native control fails at prepend resource identity on that baseline, while the new source retains it. Preserve that red baseline; this is a native resource relation, not a user latency or CPU comparison.

Test dependencies were absent from the frozen installed product interpreter. Six small testing packages were installed only into the owned .artifacts/source-sanity-deps target, leaving its product package files unchanged. They will be removed after evidence retention. The initial missing-pytest log remains explicit. Current new-source installed saved-history/frame/CPU gate remains pending; parent283's new native trace can guide the next source step without repeating capture.

## Preserve active scroll animation during the same document projection

Current accepted283 RecordAnchor._restore called Widget.scroll_to(animate=False, immediate=True) even when compensation was zero. Native scroll_to and _scroll_to force-stop both original axis animations, apply their end values and completion callbacks, then overwrite the scroll position/target. Its preceding release_anchor also reset the destination. This consumes compensation as a fresh user scroll and interrupts loading-time movement. TailAnchor and HistoryWindow.check_follow had the same cancellation seam. ReaderPosition restoration and explicit End remain deliberate navigation/user operations.

Reuse Animation's existing family: transform_values belongs to each original SimpleAnimation/ScalarAnimation operand owner. Animator.transform_running_animation consumes its original running registry, without replacing the animation, changing easing/start/duration/deadline/callback, scheduling another timer or copying status. Native scroll producers create running numeric SimpleAnimation immediately; delayed style requests remain their original scheduled resources, outside this running projection API.

Toad284 WindowRestoration.geometry projects the native destination and original running curve by the outer transaction's actual compensation once. Nested size/layout restorations do not double-project. RecordAnchor, TailAnchor and check_follow apply their existing policy through the original reactive scroll_y, preserving native bounds, scrollbar and UpdateScroll ownership. DirectionalPreparation receives the same delta. The frame gate and native mount/readiness fences remain unchanged.

Full declaration/caller census: one Animation ABC; only existing SimpleAnimation and ScalarAnimation subclasses in source/tests; all three implement the new contract; sole current product consumer is Toad WindowRestoration. No additional classes, lifecycle flags, animation/row registries, clocks or compatibility API.

## Scene damage delivery closure

Exact capture05 correction: the RGB body crop (499,70,1229,711) is byte-identical between preceding End/idle, A-return and Undo. The older text is original A saved AssistantTranscript; diagnostic live_blocks includes saved descendants. Prior B/body-difference attribution was incorrect. Full-frame changes are native tab/sidebar remembered keyboard selection plus editor caret/draft. Scoped physical A-body return holds for the previous072 source; latest559 still requires its affected installed gate. Full smoothness/CPU/concurrent busy sidebar remains open.

Source review exposes a separate incomplete scene-publication contract: _damage_geometry retains rectangles but never admits its native root message pump. In particular full_map publishes geometry during a query after the old native update timer can already be paused. Pending damage is not itself a new message; Screen only resumes its existing timer on native idle. Extend the existing damage producer to carry its actual existing root transiently and check_idle whenever its original damage ledger is nonempty. All three callers (reflow, reflow_visible, full_map) migrate. MessagePump.check_idle coalesces through the original running queue; Screen, batch admission and viewport paint readiness still own delivery. No new scheduling owner/timer/copy/flags, no gate bypass, no global repaint. Native clipped old/new rectangles remain unchanged. This is code-based lifecycle closure, not a claim that it alone explains the physical mismatch. Final installed validation pending.
