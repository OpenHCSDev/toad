# Relative-height measurement source

Widget's original height-dependency resource now holds the separate computed
box and relative-descendant answers under its original structural/layout epoch.
It does not derive relative stretch from content or box independence.
Unchanged native descendants answer through that resource instead of walking
their children again. Paint-only refresh does not retire it.

NodeList publishes membership, display constraints and prune admission to
ancestor epochs. Styles publishes actual geometry-rule changes through the
measurement owner before idle, including raw rule writes. Authored layout
changes propagate through auto-size ancestry; the relative query stops at
fixed-size children. Reparenting invalidates old and new native custody.

The original query remains live for custom container, child-list, display,
relative-height and scalar implementations. Source uncertainty propagates
through the actual auto-child path; it is not inferred from labels or bounds.
Custom content/layout behavior remains governed by its separate HeightDependency
declaration and is not used as a certificate for relative stretch.

Direct message-pump closure also changes native display before detach. The
existing pump now supplies a polymorphic closing hook; DOMNode publishes the
same NodeList update used by prune admission. This completes the native source
lifetime rather than keeping a stale relative answer until physical removal.

21 affected checks passed across the retained logs: 17 first-pass positives,
three corrected authored checks, and one live child-selection check. Three
initial authored oracles incorrectly assumed the imperative `50%` setter keeps
a PERCENT scalar; ScalarProperty normalizes it to HEIGHT, which the original
relative predicate does not recognize. controls-first.log preserves those
failures. The corrected checks use the original FRACTION behavior, without a
product parser or predicate change.

The existing loaded source Toad App completed with empty stderr, 10 tabs and
568 widgets, growing to 592 after three authored response appends. Every height
answer matched the original Git property on the same acquired tree; queries
preserved actual geometry before and after those content changes. Five
alternating unprofiled trials of 20 query sweeps measured median 54.24→45.86ms
loaded and 58.61→46.55ms after the authored burst. In the latter actual cProfile,
is_container calls fell from 18,840 to 4,126. This is query work, not a live
frame/whole-burst speed claim. The authored burst completed to idle in .262s;
there is no original-versus-changed burst-latency comparison.

The final closing-hook rename is a complete declaration/caller rename to
_message_pump_closing, avoiding the event-handler namespace for a custom
Closing message. Original transition conditions remain explicit; an already
closed pump does not republish its display retirement.

Custom getters without native mutation publication remain live, and their
ancestors cannot retain an uncertain answer. Native membership and rules must
still be changed through their original owners; direct replacement of private
NodeList/RenderStyles storage or mutation of native declarations without a
source publication is not certified by these epochs. External dynamic source
resolution cannot be established by the lexical AST record alone.

No provider/input, package/public runtime or saved-data operation is part of
this change. Original profile gaps remain correlation, not duration attribution.
Matching installation and live scroll/burst acceptance remain Parent's work.
