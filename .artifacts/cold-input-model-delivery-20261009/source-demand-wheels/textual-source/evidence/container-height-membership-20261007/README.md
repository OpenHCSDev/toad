# Native container membership during height measurement

Native `is_container` is true for either committed child membership or an
explicit layout. Child membership now answers first, avoiding RenderStyles
layout resolution on every populated step of a relative-height traversal.
Empty native child lists still consult the current layout declaration.

This changes only the original Widget property. Subclass property overrides,
relative percentage/fraction admission, hidden children, auto-size propagation,
layout policies, measurement generations and reparenting remain unchanged.
NodeList owns real child membership; RenderStyles owns the independently
changing layout declaration. Neither answer is stored or inferred from bounds.

The recursive relative-height query remains necessary: even independent
Stream content measurements can have auto boxes stretched by relative-height
descendants. Removing that query or treating content independence as box
independence would change geometry. This patch removes a predicate cost; it
does not claim to remove descendant traversal or solve burst frame latency.

source.json records existing Package AST declarations and consumers across
249 native and 288 Toad modules, with zero parse omissions. Runtime replacement
of the entire is_container property continues to dispatch normally. Private
replacement of native NodeList/RenderStyles with side-effectful nonconforming
objects is not a native measurement contract.

64 affected measurement/arrangement/structural-generation checks passed in
4.33s. The existing loaded source Toad App completed with 568 widgets/10 tabs,
equal relative-height answers for every widget, unchanged geometry and empty
stderr. It compares old/current short-circuit order on the same acquired tree.
Five alternating unprofiled trials of 20 query sweeps had medians 49.73ms and
47.92ms; trial variation overlaps, so this is not a reliable latency improvement.
The cProfile files retain instrumentation output; summed recursive cumulative
values are not an aggregate wall-time result and are not used as speed evidence.

No original session, submitted input, provider, package or public App is used.
The full recursive descendant query remains the outstanding cost; this patch
does not justify bypassing it, storing another readiness/dependency answer or
claiming the original 2.869s writer gap has been solved.
