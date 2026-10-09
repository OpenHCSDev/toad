# Style mutation and geometry ownership

Extend the existing Styles / StyleProperty mutation family so geometry damage
is decided by the rule declaration for typed, compiled and raw writes alike.
Use the existing native geometry lifetime; introduce no second revision counter,
property-name policy table, state mirror or cache.

Current source publishes every rule mutation through Styles._mark_updated and
DOMNode._style_rules_updated. The same descendant style epoch invalidates
Widget.arrange's height proof, box-height proofs, box reuse and subtree geometry.
That epoch remains necessary for inherited paint and retained rendered rows.
Raw set_rule, clear_rule, merge_rules and reset can intentionally omit repaint.
Their geometry effects must nevertheless reach the original geometry owner.

Migrate the complete mutation and geometry-consumer family together. Existing
HeightDependency behavior keeps unknown/custom measurement conservative. Keep
global paint epochs and Toad's retained-paint style epoch intact. No App, Screen,
Animator, Throbber or Toad changes are owned here.

Source-first review used the existing NRA Package parser across all 249 native
modules, with zero omissions. Relevant source consumers are Styles' five write
paths; descriptor setters/publication; DOMNode's style projection; Widget.arrange,
_box_depends_on_available_height and _get_box_model; SubtreeGeometryKey; and
Toad RetainedPaint's separate pixel validity. Static references do not establish
dynamic method resolution: descriptor MRO and custom measurement hooks require
semantic review. Full before/after evidence will accompany the implementation.

Batch sanity checks after the coherent implementation, followed by one joined
changed installed saved-history motion/profile journey with Heisenberg. Preserve
all prior source, films, failures, uncertain inputs and immutable installed
prefixes. No new worktree, environment, recording or provider call for this scope.

The original 36/37 profile shows height-proof traversal during native arrangement;
compressed stack transitions do not establish its duration or CPU share. No
performance gain or smoothness claim is made before changed qualification.
