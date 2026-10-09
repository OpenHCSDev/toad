# Rule declarations own selector matching and specificity

Reuse the existing native checkout after merged45/46; no new environment,
recording, provider or scene/cache/type. Native CSS model/match/stylesheet is
owned here. Heisenberg owns the sole Toad Workspace consumer and next joined
installed workflow.

Source-first complete native/dependency AST and semantic reading found that
DOM query already uses SelectorSet.check correctly. Stylesheet._check_rule
bypasses that owner via _check_selectors; even compound target-only rules scan
the full ancestor path. RuleSet owns selector declarations and specificity.
SelectorSet owns selector matching. Extend those existing owners and delete
_check_selectors/Stylesheet._check_rule and every import/caller together.

SelectorSet.check(node, *, css_path_nodes=None) may borrow the existing original
per-pass path resource for relational matching. It does not retain another path
or answer. Target-only matching keeps live class/pseudo semantics and requires
no ancestry. Stylesheet.apply already acquires the path for its original cache
key and will reuse it; this change does not make each relational rule acquire
another path. RuleSet.check yields declared specificity from matching groups.
Toad Workspace consumes that behavior directly instead of a private stylesheet
checker and eagerly acquired path.

Preserve external TCSS grammar, combinator backtracking/order, custom CSS path,
pseudo classes, mutable parsed selectors, specificity/initial/cascade/cache
semantics. Existing parse owners remain unchanged. No CPU dominance/gain claim:
this removes a confirmed owner bypass and unnecessary matching work, not a
measurement. IMPL-12/13 and BOUND-2 apply to the bypassed owned behavior.

Batch coherent family implementation before final bounded CSS/native-App sanity.
One next meaningful installed UI change supplies physical qualification; no
unchanged45/46/405 gate or new capture. Before/after source evidence records
parse omissions and ambiguous dynamic resolution honestly.

## Source-qualified working checkpoint

Production frozen34c18a55c8a0eab2e20f22cee275f82a039e7132: three production
files67 added /83 deleted against merged45/46 maincd81c620. No DOM/query/scene
patch was needed: its target selector behavior already derives correctly.

SelectorSet.check now owns the original relational backtracking algorithm,
including target identity, combinators and selector.advance. Module-level
_check_selectors is deleted. SelectorSet.is_compound derives the existing
selector declaration's target-only question on demand; there is no saved flag
or different classifier at another layer. Mutable declaration edits remain live.

RuleSet.check owns matching declared specificity. It acquires the original CSS
path once, only when a relational group needs it, and shares that resource
across all alternatives. Its optional path parameter is a borrowed pass resource,
not absent semantic state. Stylesheet.apply lends its already acquired path;
Stylesheet._check_rule and import are deleted. Cascade, default/initial values,
cache keys/source order, candidate planning and style publication are unchanged.

Heisenberg migrated the sole Toad Workspace caller atbfd41612b1b90982b88e5db5ed7b53e0f0abfa24:
rule.check(node) replaces the private stylesheet checker and eager path. His
same change deletes Workspace's independently authored CSS type roster and
pre-filter, deriving actual targets from the rule instead. His Toad file is
read-only here. No other native or Toad production caller retains either deleted
checker. Native and Toad before/after AST parse249/289 modules with0 omissions,
including matching declarations and imports. Syntax evidence cannot resolve
external dynamic overrides; custom CSS-path semantics are preserved and checked.

## Final batched sanity and preserved negative

The45s bounded native/CSS batch reported18 passed/1 failed in1.02s,exit1.
The failing explicit expected-results table authored here incorrectly treated
bare DOMNode as a CSS type. Original DOMNode declares an empty _css_type_names;
its __init_subclass__ registers subclasses. The existing matching result was
correct. Only that expected tuple changed to three false results; production
remained byte-equal34c18a55. The one changed expected-results check passed0.33s,
exit0. Original native-sanity.log/.exit and corrected-css-expectation.log/.exit
are retained. No unchanged whole-batch repeat or production patch from a failure.

Passing checks cover target-only class/id/system exclusion, live mutable
selectors and pseudo-classes, custom CSS ancestry, compound/child/descendant/
alternative external grammar, specificity, one path for relational alternatives,
no path for target-only rules, original hover/id/cache/source-order/variable/
source-removal behavior and native App focus/disabled updates. Existing cache
observers call the actual RuleSet.check implementation; they do not substitute
its answer. The removed private-checker test oracle was replaced by explicit
external-CSS expected results, not another matching implementation.

Headroom warning: home8.4GiB/root7.3GiB/RAM14.1GiB/swap14.0GiB. One bounded
source-Python batch used existing dependencies; no helpers, provider, recording,
new environment/native copy or public mutation. No CPU share/gain/FPS claim.

Native source qualification is complete. PR47 remains draft until the single
changed installed journey with Heisenberg's source batch qualifies this family.
Merged45/46 and405 remain independently accepted; no repeated gate or rebuild.
