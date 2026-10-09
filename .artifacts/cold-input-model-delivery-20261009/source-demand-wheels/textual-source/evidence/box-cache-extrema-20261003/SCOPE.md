# Keep box constraints with the original cached measurement

Same native checkout, normally integrated merged main/Text40. Its source0ab, Ready receipt
and installed artifacts remain frozen. No new environment/native build/movie.

Widget._get_box_model retains BoxModel in its existing bounded LRU, but selects
Widget._extrema only on cache misses. A width/height A→B→A cache hit therefore
returns A's model while alignment reads B's constraints through _arrange.
This is a source-supported mismatch; the profile shows this native measurement
path but does not establish its CPU duration or a live observed wrong alignment.

Retain the original model and original Extrema together in the existing cache
resource. Cache hits select the constraints from that exact original resource.
Keep pre-measurement constraint selection on misses: native auto-size measurement
can arrange children before the final box is calculated. Preserve public
BoxModel return/unpacking, custom resolvers, lifetime release and capacity.
No new class, map, cache, constraint algorithm, compatibility reader or geometry
policy. All private cache consumers and downstream alignment/box callers are
included; no Toad files are authored here.

AST/source first, coherent implementation then one affected sanity batch.
Any installed qualification joins Heisenberg's next changed workflow; no repeat
of qualified391/40 and no measured performance/End/FPS claim.

## Working checkpoint

One production file:7 added/4 deleted. Widget's original bounded16-entry LRU
retains (BoxModel, original Extrema), and a cache hit selects both. The active
_extrema remains an original artifact reference for recursive native alignment;
its value is not re-decoded or calculated by a second policy. Misses select the
original resolved constraint artifact before auto-size measurement as before.
Public BoxModel construction/return/unpacking is unchanged. Cache invalidation,
capacity and presentation retirement release the paired resource together.

Existing Package AST covered249 native and289 Toad modules, zero omissions.
All private cache reads/writes live in Widget; the sole downstream constraint
consumer is native _arrange alignment. Native grid/dock/split/resolver callers
keep their original BoxModel contract. After source records the changed owner;
other roots are unchanged. AST cannot establish unknown dynamic/private callers.

Final sanity:44 existing box/lifetime/height-arrangement cases passed in3.55s;
the new real App cache-return case first failed because its test helper read
DockArrangeResult.placements as unindexed entries. That source contract is now
(ordinal, WidgetPlacement). The original negative remains, production unchanged.
Corrected only that consumer; reran only the affected case:1 passed in0.40s.
Its actual native center alignment is18 cells after A80→B160→A80, with retained
A model and exact original A Extrema identity. No mock App/protocol or patched
constraint resolver. The unchanged44 cases were not repeated.

Installed qualification remains pending Heisenberg's next changed393 workflow.
The original391/40 recording is protected, with no extra movie/provider/env.
This fixes source-derived cached constraint selection, not a claimed observed
user alignment failure or measured performance improvement. End, chunky motion,
channel first paint and the full native performance goal remain open.

Normal main/Text40 integration uses862da48c; production remains byte-equal
with the qualified-source follow-up d6ddd054c. No semantic conflict, new native
checks or repeated capture. The existing joined393/41 qualification waits only
for release of the parent/Sch588 borrowed holder, which was not modified.
