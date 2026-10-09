# Reduce original damage intervals once per vertical band

Base: merged Text68 dd625069e50cc0b909832b549a485abc55067149.

The existing `Compositor._regions_to_spans` expands every damaged rectangle
into one interval per row, then sorts and merges the same active intervals
again on each row. Output rows are necessary; repeated interval acquisition
and union inside a band without rectangle edges is unnecessary work.

Keep that original reducer and its exact ordered output. Use rectangle start
and end edges to reduce active horizontal intervals once per changing vertical
band, then emit those original spans on each required row. Preserve overlap
multiplicity, touching intervals, gaps, negative origins and complete bounds.
No new retained resource, cache, map, timer, flag, type, API or Toad caller.

The complete Package AST before/after from Text68 is retained as caller
source evidence: native249/tests460 and Toad288/tests397/tools41 with0parse
omissions. The current reducer has four native callers and seven test callers;
all render paths continue to use the same owner. Dynamic private-method
rebinding and unregistered external callers remain unproved.

Source reasoning and coherent implementation first; final proportionate
interval and affected native App controls last. Native68 original14+2 controls
and negative are immutable, not rerun. No build/installed prefix/SDK/provider/
media purpose; no measured gain or physical cadence claim.

## Published algorithm and caller closure

Production83ea6b17eab3ac0a917451070a954b7299a1a91a, one file23+/23-.
The original reducer now consumes each input rectangle once into its vertical
start/end edge deltas. Counter preserves original overlapping interval
multiplicity; intervals are reduced only when that active set changes at a
vertical edge. Each required output row still receives the original ordered
spans. Empty gaps are skipped and no source rectangle is expanded into a
per-row temporary range list. Counter.elements preserves original interval
multiplicity before merging; no retained state survives the generator.

`owner-consumers.json`: actual source48f79749ef7521ff727cbc7be0feba1794e99c6a,
production249/tests460, parse omissions0, one reducer declaration and four
native consumers. Original Text68 pinned Toad dependency census is retained;
all source signatures and related consumers remain unchanged here. Existing
full, partial, inline/export and original-body capture paths use this reducer.
One source fact remains one owner; no separate fast path or uncached reducer.

## Final pure source controls

ONE batch8PASS/0.18s, controller1.3053654759423807s, exit0. Source48f79749e,
production83ea6b17e. Exact logSHA
`c513a336404899b0e4e59540faac60f730d81e38e236b1b942334605c26575ed`.
Existing empty/single/partial/full overlap, different-row and same-row gaps,
and adjacent intervals passed. The added whole-contract case preserves
different rectangle lifetimes with equal horizontal spans, negative origins,
one-shot input, distant empty gaps, nonpositive height and original
zero-width span output. No App, installed prefix, SDK/native process, build,
provider, media or accepted Native68 controls were run.

Draft / pure source-qualified only. No installed frame/materialization or
physical scrolling result is inferred. Full observed source/paint workflow
acceptance belongs to the next meaningful joined Heis cohort; issued46067 is
unchanged. CPU time and cadence are unmeasured. Band reduction still sorts
active intervals at each real source edge; it does not remove legitimate
output rows or promise a universally faster result for every damage shape.
