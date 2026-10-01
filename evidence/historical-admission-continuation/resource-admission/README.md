# Original native working-set admission at historical source trimming

Owner Heisenberg, PR269. Normally integrates main d0349869 and the complete266
checkpoint. DocumentViewport owns the bounded native body working set, its
original weak LRU, measured costs, widget and renderer-byte limits. TranscriptHistory
previously retired whole source fragments by a separate nominal item limit even
when this same native working-set admission would retain them. Source roots
were repeatedly reconstructed despite available native resource capacity.

Expose the existing DocumentViewport admission calculation and use its result in
TranscriptHistory's existing fragment budget. Required native-visible, selected,
focused, newly admitted and anchored resources retain their existing protection.
The original widget-cost trim and empty-page overhead bound remain in place.
No page registry, resource-cost copy, semantic state, new timer or second renderer
is introduced. The policy still owns nominal item reserve and three-viewport
runway. A new body family implements the original ViewportBody resource contract;
no consumer case is required (IMPL-13 and IDEN-5 ownership).

Matched native Toad/Pilot diagnostic, 80 original synthetic source fragments,
15 PageUp/15 PageDown/15 reverse/End, no Agent/provider/public root:

* Baseline constructs275 fragment bodies; candidate119, both80 distinct source
  fragments. This is construction instrumentation, not a CPU or paint metric.
* Candidate settled peak299 native widgets within the original300 bound;
  body retirement remains active (12 native body evictions).
* Both original application diagnostics complete without an application exception.
* These source/resource counters are not installed saved41MB acceptance.

The existing projected-history test first failed because it patched deleted
_warm_pages. Delete that obsolete patch, retaining every behavioral assertion.
An inline diagnostic failed multiprocessing spawn (<stdin>); its logs remain.
The corrected persistent driver runs original exercise80/800 on real Toad.
Both installed baseline and candidate fail exactly (800,20,19) at the same
projected item-bound assertion; exercise80 passes on both. This pre-existing
contract mismatch remains OPEN, and is not rewritten as a passing guard.

The matching counter receipts and all failed diagnostics are retained here.
Rich native materialization diagnostic passes with30 source records,20 list
items each,three Up/Down/reverse inputs and End. Recorded peak289/300 native
widgets,18 body evictions,Agent unbound and no application exception. The
longer15-input run timed out with no verdict and remains preserved. Its fragment
construction index used equality, which conflates repeated identical list bodies;
no rich source uniqueness or reconstruction claim is made. The observer now
uses original fragment object identity; no optional repeat is needed for the
independent native widget-cost measurement.

The affected immutable installed original-history journey remains pending. No READY, live activation, total CPU gain, Strip reuse,
whole-frame gap closure or final latency claim is made from these counters.
