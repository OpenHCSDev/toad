# Actual placement mode owns measurement dependencies

Ordinary fractional-width placement resolves its fraction without querying
content width. Optimal sizing turns that width into auto and queries it. The
previous height proof conflated these operations, preventing ordinary content
height measurement and placement from sharing their existing arrangement.

HeightDependency now carries the actual greedy mode. Flow forwards it to child
boxes; Widget derives it from optimal for arrangement and passes greedy from
the box resolver. Existing dependency resources retain both answers under their
original structure/layout epoch. Actual result resources already keyed mode;
no new resource or result cache was added.

Native content-height algorithms still use normal arrangement regardless of
outer box mode. Native content-width uses zero-height optimal arrangement.
Stream directly measures content; Grid keeps its conservative track proof.
Custom hooks, relative heights, docks, splits, overlays and alignment retain
their original dependencies. Width, viewport, style and child mutation remain
inputs. No placement or rendering algorithm changed.

## Source and checks

Existing refactor-audit Package parsed 250 native modules, zero omissions.
All HeightDependency implementations live in _measurement.py. Widget owns both
source resources and box/arrangement consumers; Layout declarations choose the
content algorithms. Current Toad declares native measurement policies but no
custom HeightDependency subclass. No Toad source changed.

Four affected controls passed in 0.49s: mode-specific custom width, ordinary
arrangement reuse, width/style/child changes, nested flow and unknown overrides.
The first new control incorrectly treated indexed (ordinal, placement) tuples
as placements; its AttributeError was corrected at that original test reader.
No product correction was made in response to that fixture error.

One existing raw Driver drag-settled App completed with source native and the
installed owned-sidebar/Content-worker frontend. Twelve source updates and the
original ready boundary preceded 36 pointer moves. Exit zero, empty stderr,
released capture, final width 60. Profiled final frame 955.09ms, 8 frames,
625 final widgets. This is not comparable to the supplied unprofiled 747ms
result; no user-visible speedup is demonstrated.

Inclusive profile: 8 root arrangements 462.58ms; box resolver 902/321 calls
300.62ms; Layout.get_content_height 291/68 calls 258.45ms. These costs overlap
and are not summed. Different widget/frame counts prohibit reliable comparison
with the prior installed profile. Width-dependent content measurement and
placement remain expensive. This removes a false dependency, not that work.

Raw logs and profile:
/home/ts/.cache/agent-scratch/native-arrangement-input-mode-20261007/
(native.log, app.stdout.log, app.stderr.log, drag01/result.json, drag01/ui.pstats).

No package, provider, public owner or installed pin changed. No standalone
build requested on the strength of this result.
