# Complete placed geometry supplies narrower requests

Native PlacedSubtreeGeometry previously required the capture visible_only flag
to equal the request flag. It therefore discarded an unchanged complete source
when the next transaction requested only visible geometry. The compositor also
bypassed any partial-mode resource when acquiring a retained path, even if its
original capture was complete and already owned that path.

The existing resource matches method now accepts require_complete. Placed
geometry permits complete-to-visible requests only when every other key field
matches. Partial-to-full remains a miss. Retained requests require the original
complete capture, while IntrinsicSubtreeGeometry retains its existing complete
source and original intrinsic matching. No new state, cache, capture format or
projection behavior. The compositor delegates to this one answer; an incomplete
or changed retained source still uses the original uncached path acquisition.

Facts independently forcing placement remain geometry/child revision, width and
height, viewport size, region, rank, clip, visibility, dock gutter, inherited
layers and scroll offset. Authored mutations and held-root invalidation remain
unchanged. Full acquisition/viewport projection are different requests against
one complete source, not different source identities. Partial captures cannot
invent offscreen geometry. Existing spatial projection handles actual entries.

Source audit with original Package:250 production modules, zero omissions;
SubtreeGeometry plus both concrete matches implementations migrated, one caller
in Compositor.add_widget. No external dynamic resource override is inferred from
lexical source. Public custom arrangement and coordinate behavior remain bound
to the original CACHE_SUBTREE_GEOMETRY opt-in and native key contract.

Three real native App checks passed1.19s. Complete capture to visible plus an
actual offscreen retained row performs zero subtree arrangements; cache-disabled
native reference agrees on visible geometry and retained coordinates. Changed
scroll, partial-to-retained/full and changed child arrange. Existing fixed,
viewport/overlay, resize, full-map and rendering controls remain correct.

One original history_check.py App run used readonly installed selected-memberships
delivery runtime Toad/Core, replacing only Textual source2d85b8e9. Imports/command
stdout retained under /home/ts/.cache/agent-scratch/native99-channel-history-20261007.
HISTORY_PROFILE=0;160 authored initial private wire messages,20 incoming and30
PageUp. No provider/public inputs, package writes, native build or pin change.
Terminal0, empty stderr, no App exception. Result:53 mounted rows/oldest113,
p95 loop16.20ms, maximum126.83ms,6 intervals above50ms. Actual runtime/Toad changes
and different final workload invalidate comparison against the earlier120-row
run. The driver asserts App health, not complete pagination or exact reader
position; no full paging or overall speedup claim. Significant pauses remain.
The original runtime_fixture joins teardown; controller joined and no driver
process remained. Exact child births were not recorded. Parent owns Toad
consumer followthrough and durable delivery; no extra App rerun performed.
