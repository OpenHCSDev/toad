# Working source checkpoint

Production deletion: **1 line replaced**, 7 lines added in worker_static.py.
Source checkpoint74cccbb5; production change5b017836. PR256 is a contribution
to Heisenberg's PR254 integration, not a competing release or capture owner.

## Canonical relation and consumer closure

Textual Widget.outer_size exposes the original committed geometry resource.
Native _size_updated commits that resource before posting Resize; native Resize
coalesces older events. WorkerStatic reads the current public resource rather
than holding another size or relying on an older event payload. The fixed-width
content bound is outer size minus its declared style gutter. Offscreen geometry
remains the original native committed resource until exposure publishes Resize.

Global screen layout invokes preparation only for auto-width, which still uses
the original parent.scrollable_content_region bound. Existing source/style
invalidation, generation, wanted/ready task resources and worker admission are
unchanged. WorkerStatic.render_line still uses native visible geometry. The
direct consumers are ReadToolOutputPart, FileKind preview composition and
FilePreview readiness; none acquire another width authority or consumer branch.

This removes the BOUND-2 ownership bypass whereby a global layout observation
materialized the full compositor scene merely to compare an unchanged rendering
request. No semantic mirror, private size probe, width cache or flag was added.

## Actual continuous source journey

Driver157 lines uses native ACP ToolCall model decode once, ToolCallStatus,
real ToolCall widgets admitted by original Contents, ToadApp, native compositor
and actual default background workers. No Agent, provider, ACP substitute,
patched render method or fake UI is involved. It warms12 expanded Read tools
through native geometry, publishes25 original visible layout relations, sends
actual PageUp/PageDown/reverse keys, then verifies resizing/reveal, padding,
color, source paint, auto-width parent resizing and resource disposal.

| Measured native layout/scroll phase | Installed85 baseline | Candidate source |
| --- | ---: | ---: |
| Full scene arrangements inside WorkerStatic preparation | 212 | 0 |
| Preparation requests | 2832 | 0 |
| Retained prepared resources reused | 12/12 | 12/12 |
| UI process CPU seconds | 6.791 | 5.297 |
| Profiled wall seconds | 10.877 | 10.803 |

The baseline used installed Toadd85d45b51. Candidate imported this worktree's
Toad source on main34a2ced3. Both used installed Core970/Text6b/SDK0.12.1
from runtime-source-publication-custody-20260930. The actual call-stack counters
attribute the removed full-map work; the CPU observations include the full UI
phase and are not an isolated performance estimate or tab-latency claim.

Commands use that runtime's Python, WORKER_SIZE_OUTPUT under the owned worktree
and candidate PYTHONPATH=the owned src only. Baseline removes PYTHONPATH. Both
execute tests/worker_native_size_pilot.py; private roots are temporary children
of the persistent owned artifacts directory. Zero provider calls in both.

The first candidate run failed resource reuse before warming all native widths.
Its exact negative receipt is retained. Cold first exposure legitimately changes
wrapping; the corrected driver warms through each original ToolCall before
measuring strict reuse. The installed baseline then fails the unchanged zero
full-map assertion. The candidate passes reuse plus every affected size/style/
source/disposal check. Raw receipts and the baseline traceback are committed in
raw/. No original failure was replayed or discarded to claim acceptance.

## Remaining boundary

This is a useful working source checkpoint, **not installed or physical Ready**.
Heisenberg integrates the contribution into254; parent owns coherent staging
and default activation. Existing recorder/video+CPU on the combined actual
candidate remains required. No second capture or installed package mutation
was launched. General UI CPU cost and auto-width parent-map cost remain outside
the fixed-width result. No final performance target is claimed.

Resource check before the bounded source journey reported home10.2GiB,
RAM19.1GiB and swap8.9GiB warning. Runs were serial, no native owners/providers
or extra helper fleet. Generated output is40KiB; selected raw proof is retained
for review and generated leftovers may be removed after handoff.
