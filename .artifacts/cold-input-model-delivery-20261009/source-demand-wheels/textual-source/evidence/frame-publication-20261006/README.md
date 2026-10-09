# Independent frame publication

Native Screen asks its existing preparation owner for deferred Widget roots.
Compositor derives held rectangles from committed geometry, retains their damage,
and publishes other spans through its existing chops and inline formats.
BackgroundScreen borrows the same admission during the synchronous render.
The original callback queue admits senders outside held subtrees; containers of
a held subtree also wait. Screen reports the exact acquired roots only after an
actual non-None display. The application writer remains responsible for flush.

Mutation roots borrow original committed placements during arrangement. Native
box measurement uses those placements rather than descending into changing
children. The existing scene map remains the geometry owner. No second queue,
timer, damage store or compositor is introduced.

The shared Toad contract is `_prepare_compositor_refresh() -> tuple[Widget, ...]`,
`_layout_mutation_roots() -> tuple[Widget, ...]`, and
`_on_frame_published(deferred_roots: tuple[Widget, ...])`. Parent owns Toad #482.

`before.json` uses the existing refactor-audit Package parser over all 249 native
production modules and 461 test modules, with zero omissions. Its 259 lexical
sites identify definitions and references; dynamic subclass and callback
resolution was read semantically, not inferred from absence.

This remains a draft pending the matching Toad application journey owned by
Parent. Native checks passed: 17 in 1.76s for batch/publication and scene-damage
semantics; then 12 in 1.69s after completing polymorphic sender/backdrop admission,
including inline, translucent, mutation/hit geometry, quiescence and reparenting.
The first focused run refused an ambient-App sidebar callback; the receiver now
owns admission. A later test incorrectly expected a Label at an original cell
owned by its container; the control now compares the actual pre-mutation hit.
Both original negative tool outputs remain in the session. Logs here retain the
final successful checks and the intermediate hit assertion refusal.

Parent's first matched source App at 225c did not finish and was joined. Its
successful stack observed held-callback idle work; its later empty stack file
is not evidence. The held queue entry called check_idle on every pass. That
wake-up is deleted, and held-only damage no longer resumes the original timer.
No new timer or wakeup mechanism was introduced. New source still requires the
changed matching application check; no latency improvement is claimed.

Callback scope is polymorphic: MessagePump and Screen await the entire frame;
Widget borrows its own original screen geometry, including backdrops. InvokeLater
is delivered to the receiver's original queue before sender admission. Container
callbacks cover descendants as well as roots enclosing the sender. Mutation
placements also protect hit lookup from a sibling's still-unpainted overlap.
`after.json` parses the staged complete production/test tree with zero omissions;
it records the actual declaration/MRO hooks and lexical consumers. The frozen
textual-native-subtree-strips checkout is unchanged.
