# Existing body resource and worker publication

Before AST: production288/tests391/tools41 parsed with existing refactor-audit
Package; zero omissions. Native40 has its own whole-owner source closure.
Dynamic method resolution is a semantic read, not proven by name matching.

BodyMeasurement owns the contract; MeasuredBody owns measured dimensions;
LiveBody and RenderedBody reuse that declaration. MaterializingBody references
its preceding resource and actual Worker. Removed its independent three extent
fields/default zero-paint/unready decision. Pending source updates keep only
valid retained pixels; a previous live or measured tree still blocks painting.
All width/height/cost/paint/selection/style/resize/LRU/restore/input and worker
completion consumers use that family. Selection's content-field probe and the
Live-height write that replaced a pending writer are deleted. Worker identity
owns completion/failure even when style/size/release replaces its resource.

The next worker borrows an AwaitComplete of the prior Worker wait, not a closure
holding obsolete paint resources outside LRU accounting. Native mutations keep
the original history-lock/frame fence. No new store/cache/queue/scheduler/flag.
All three existing body implementations inherit the algorithm unchanged.

Production39 lines deleted/140 added (includes moving existing MeasuredBody
above LiveBody); existing family and consumer migration, no added body class.
One batched installed App check covers pending retained paint/cost/interaction,
style/release/writer commit, queued source/theme/append and cancellation. One
actual public saved-history motion/profile journey is preserved in READY.json.
No overall speed/CPU/144Hz claim. Prior384 and all raw negatives remain intact.
