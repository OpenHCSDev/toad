# Scoped native body readiness contribution

Production delta against aec56e08: **10 lines deleted, 12 added**, two files.
Deleted `TranscriptFragmentView.body_ready`'s repeated descendant census. Its
existing base declaration reads native mount and original dormant/restoring
resources. Frame admission asks original compositor-visible body resources
within the original Window ancestry. Whole-fragment retirement retains the
descendant readiness check because pruning removes hidden resources too.
No additional readiness state, registry, source copy or semantic cache.

One continuous actual Toad/Pilot resource journey passed in source05:

- Initial native Mount joins held nested Markdown parsing.
- Later nested Mount is independent of the already-mounted parent. The native
  compositor does not expose that pending child yet; pruning still refuses it.
- A mounted visible nested body is retired through its original resource owner.
  Frame readiness refuses its dormant and asynchronously restoring resource
  while its parent remains mounted and locally ready.
- Releasing the parser restores the actual nested body and frame readiness.
- Whole-root retirement removes descendants, and asynchronous recomposition
  restores the original source. Actual compositor strips contain
  `NATIVE_BODY_READY`; restored.svg preserves the rendered frame.
- Profiling 100 frame-readiness queries records zero `walk_children` calls.

Command used installed249's Python with this contribution's source on
PYTHONPATH; this is source/resource acceptance, **not installed readiness or a
physical CPU/speed claim**. Actual Window, native widgets, AwaitMount, parser,
retirement/restoration and compositor are used. The test parser holds the
original asynchronous operation; it does not replace application/protocol state.
No provider calls or public mutations. Heisenberg253 owns normal source
integration and one affected original-history scroll/video/profile acceptance.

Raw source01–04 failures are retained: wrong direct fragment mounting bypassed
the nominal contents contract; Pilot idle waiting during a deliberately held
Mount was inappropriate; incomplete child Mount is not yet compositor-visible;
empty AgentResponse does not imply a loading resource. These test assumptions
were corrected rather than changing product state to satisfy them. Source02's
owned interrupt and birth-checked renderer cleanup are retained. The final
source05 cleanup census finds no processes bearing this owned evidence route.

Patterns: BOUND-2, IDEN-7 and IMPL-5. Native Mount completion and body readiness
remain separate original resource observations. Existing budget, measurement,
reconciliation, presentation publication and user-input owners are untouched.
