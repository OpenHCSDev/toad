# Native warm-set trimming checkpoint

Heisenberg owns DocumentViewport production; Kepler owns physical recording and
profile correlation. Normal main integration includes merged227 and235. This
does not repeat227's completed original-source resource gate.

## Cause and change

The retained224 profile has an End-transition sample at35.557s in
`_trim_warm -> widget_count -> walk_children -> walk_depth_first`. Its sampling
alignment cannot prove that function caused the old33ms physical gap.
Source inspection establishes a separate concrete cost: every LRU eviction
recounts every surviving native tree. The unchanged window owner now measures
each tree once in that synchronous pass and subtracts each evicted tree's cost.
No DOM mutation or suspension occurs during measurement/eviction. Costs are
local to this invocation, not a persistent resource cache or semantic mirror.

Existing byte/widget budgets, LRU order, focus/selection protection, body
retirement/restoration, source validation and worker admission are preserved.
Future ViewportBody implementations still supply their existing resource
contract; no new case needs a consumer edit. IDEN-5 prohibits retaining a second
authoritative count; this change computes temporary costs from the native DOM.
The single-file audit parses both versions and adds no dispatch or debt counts.

## Actual source UI counterevidence

Use the existing installed dependencies with this checkout's source:

```sh
TRIM_EVIDENCE="$PWD/.artifacts/warm-trim-candidate-unprofiled" \
PYTHONPATH="$PWD/src:$PWD/tests" timeout 45 \
.artifacts/installed-warm-admission/bin/python tests/viewport_warm_trim_pilot.py
```

The real ToadApp mounts24 actual AgentResponse Markdown trees,552 widgets, and
applies the actual window budget. No fake application/body, ACP process,
provider input or original-thread attach. The baseline fails the repeated-walk
assertion; the candidate passes, preserving the same four LRU bodies/92 widgets.

| Same native resource trim | Baseline | Candidate |
| --- | ---: | ---: |
| Native subtree walks |294|24|
| Profiled CPU |10.246ms|0.985ms|
| Profiled wall |10.283ms|0.986ms|

Candidate unprofiled CPU0.277ms/wall0.281ms on the same still-mounted trees and
same restored LRU order. Profiler overhead is material; profile timing is not
unprofiled latency. Raw cProfile and runner logs are retained under the named
owned `.artifacts/warm-trim-*` directories; JSON records source hashes/boundaries.

This proves native trimming work and budget behavior. It does not prove faster
41MB physical scrolling, warm first paint, Strip reuse,33ms-gap elimination or
full TC1/T9 closure. The next physical comparison belongs to the existing Kepler
recorder on a newly admitted matching cohort, without public owner mutations.
