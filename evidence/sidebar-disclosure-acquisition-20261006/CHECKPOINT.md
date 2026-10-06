# Reveal the original disclosure before clicking

Batch07 reached the 60-row range after the earlier mixed menu actions, then native Pilot refused an off-screen disclosure in reveal_thread_row. The helper revealed only the member after clicking the collapsed channel.

The existing helper now scrolls the actual disclosure into view and lets native layout settle before the same real Pilot click. This is the existing first-fork helper pattern. All four related modules keep calling this one helper; member acquisition, native hit geometry, assertions and bounds are unchanged. No production code or frozen operator root changed.

Original Package parsed 288 production, 403 test and 40 tool modules with zero omissions. Changed helper compiles without imports; all other AST declarations match and diff check passes. No installed rerun or full acceptance is claimed. Batch07 whole return retains the original failure and restored floor.
