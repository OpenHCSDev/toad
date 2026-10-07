# Prepared Rich publication owns layout demand

WorkerStatic previously requested layout for every completed render, even if its original PreparedRichContent width and line count were unchanged. Those are exactly the facts used by its native get_content_width/get_content_height. Publication now derives layout from the previous and incoming prepared results. Paint-only updates refresh paint; changed dimensions still refresh layout. The existing IRCMessageText publication hook borrows history compensation only for changed geometry. Source/style/width currentness, original render workers and retirement remain unchanged. No extra stored dimensions, cache, renderer or queue.

Complete src/tests AST parsed698 files with zero omissions: one base hook, one IRC override, two callers. Both migrated together. Changed owners compile/diff-check pass.

Actual native IRC App passed a color-only update with equal source text/width/line count, observing its original refresh(layout=False), then full-width wrapping at80/36/120 columns, actual clickable sender/destination spans and keyboard navigation. Output was terminal0. Source run uses current installed Core/native with changed Toad source; this is not installed/default delivery or a frame-time improvement claim.

The older worker_native_size_pilot refused before worker acquisition waiting for ToolCall WorkerStatic descendants. A proposed reveal-order correction also refused; its hypothesis is unproved and that helper edit was withdrawn. Both negatives retained at /home/ts/.cache/agent-scratch/worker-paint-extent-20261007/failure.txt and /home/ts/.cache/agent-scratch/worker-paint-extent-corrected-20261007/failure.txt. They provide no new production-cause claim or twelve-tool acceptance.
