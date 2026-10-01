# Native WorkerStatic preparation dependency closure

Kepler owns `src/toad/widgets/worker_static.py` resize/style/source preparation
under Heisenberg's PR254 integration. Baseline main34a2ced3. Parent explicitly
assigned independent performance implementation; Heisenberg granted the exact
methods before editing. His dirty exploratory tests stay in his own worktree.

Fixed-width preparation currently observes every global screen layout and reads
`self.size` before comparing an unchanged render request. An offscreen widget
can force native Compositor.full_map reconstruction merely to discover no new
render job. Native Resize already commits widget outer/container dimensions
before delivery. Those native resources own size, not another application copy.

Implement fixed-width preparation through native Resize, source and style
invalidation. Preserve the existing parent content bound for auto-width. Do not
add width caches, flags, registries, private native size probes or semantic
mirrors. Existing bounded Rich worker requests/results remain rendering resources.

Trace declaration, native message delivery, all WorkerStatic consumers, offscreen
retention and resize before changing behavior. Verify actual Toad ToolCall output
and original Contents admission: visible/offscreen/layout/resize/style/source,
native full-map work and prepared wrapping. Retain failed evidence. Existing
physical recorder and CPU observation apply; no X0, paid provider or competing
publication test. Focused/source proof is not installed or physical readiness.

Publish useful working checkpoints before optional broad testing. PR254 owns
normal integration; parent owns installation/default activation. Report deleted
lines and precise remaining acceptance limits.
