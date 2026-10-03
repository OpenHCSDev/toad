# Reader motion and foreground paint continuation

Source-first continuation from merged412/main5ec7876. Same checkout; no new
worktree, environment, native copy or VCS-clone packaging. Existing ReaderPosition,
WindowRestoration, HistoryAnchor, body/frame and preparation owners remain the
source of behavior; migrate related consumers and delete competing work.

Trace offset restoration versus geometry compensation before assigning the
remaining interruption cause. RecordAnchor already writes scroll_y under
WindowRestoration.geometry and translates the original animation. Distinguish
session restoration, transcript paint completion, checkpoints and filter changes
from viewport lazy reentry; do not blindly remove deliberate navigation stops.

Latest412 original motion/profile:143.203s/warm16/input7 and37 retained bodies;
Up writer p95 33.53ms/worst197.89ms, marker UI71.51%; motion remains discrete.
No overall gain/terminal144Hz claim. Reuse this evidence; no unchanged capture.

## Full unfinished performance scope

Configurable144Hz target6.944ms/frame and responsive busy/compaction input;
foregroundCPU/raster/firstpaint/coldwarm A/B/A; original boundedrunway,
velocity/reversal/growingEnd/PageDownvoid; uninterruptedanimation; IRC/DM,
tabopening/sidebar/busyactivity; focus/draft/Undo/TC1T9T4 and whole configured
user workflow. Useful qualified checkpoints ship without holding for final144Hz.

Einstein607/413 owns the sequential style22 CODE loan and menu/command source;
Heisenberg retains all body/viewport/frame/reader/preparation source. Kepler
owns native Compositor/Widget/layout. Shared edits are coordinated directly.

AST/source semantics choose the change, then one batched proportionate sanity
and changed installed motion/profile journey with personal consecutive-frame
inspection. No test-first investigation, new timers/caches/queues/mirrors,
unchanged films, provider inputs or original-session mutations.
