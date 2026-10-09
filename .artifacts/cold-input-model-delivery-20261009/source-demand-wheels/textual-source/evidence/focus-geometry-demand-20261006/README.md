# Acquire focus ordering geometry together

The installed submit trace reaches native focus reset when the focused compose
editor becomes disabled. Screen previously sorted every displayed sibling,
including branches without a focus target. Each sort key reads virtual geometry.
For an omitted offscreen node, Compositor published another visible arrangement
retaining the accumulated reader paths plus that one node. Completeness stays
invalidated, so the next missing node repeated the operation.

Screen now acquires the focus subtree's membership, disabled/loading decisions,
inherited visibility, and allow-focus hooks once in this synchronous query.
Branches without any eligible target are pruned before requesting positions.
Ancestors of offscreen targets and visible descendants overriding a hidden
parent survive. Compositor receives the complete ordering demand together and
uses its original visible arrangement with existing committed reader paths.

The resulting branches are ordered through the original `_focus_sort_key`,
including subclass overrides and stable sibling ties. Containers precede their
children as before. Focus traps select the same original root. This does not
equate viewport paint membership with full focus eligibility.

`find_widget` delegates its original single-path acquisition to the same
Compositor method. No full-map invalidation rule, retained geometry, mutation
hold, virtual-region fallback or captured-descendant refusal was relaxed.
The local branch tuples live only for this synchronous query; there is no new
persistent geometry/focus cache, queue or reader authority. No Toad edit.

## Confirmation

22 focus/geometry checks passed in 1.66s, including existing focus trap, hook,
disabled, inherited visibility and traversal controls and strict original
capture scope. The new real `run_async` check disables a focused TextArea with
40 offscreen buttons: one visible arrangement acquires all ordering paths;
unfocusable source rows are omitted; previous committed placements survive;
the unsent draft survives; ordering matches a complete original arrangement.

One loaded source Toad App used its actual PromptTextArea disable watcher with
565 widgets / 10 tabs. Under cProfile the synchronous setter took 8.106ms:
one reset, one ordering key, one geometry acquisition, zero arrangements.
Exit zero, empty stderr, original unsent draft preserved, zero submitted inputs
or provider calls. This is not a measurement of the installed channel-send
workflow, terminal repaint, or an overall latency improvement.

Raw result/profile: `/home/ts/.cache/agent-scratch/focus-geometry-demand-20261006/`.
The supplied P7 trace remains unchanged. Its changed stacks do not establish
call counts or exact elapsed time in this method.

The original Package parser covered native 249, Toad 288 and Core 324 production
modules with zero omissions. Before/after sites are retained here. No tracked
production override of the sort-key declaration was found. Arbitrary extensions
mutating the DOM or focus predicates during a sort/layout query are not proved
by this static source pass or these checks.

Not installed. Parent owns the Toad sender and live frontend delivery; no
package, artifact, original session, recorder or public-owner operation occurred.
