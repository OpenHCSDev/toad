# Persistent workspace selected-source navigation latency

Continuation from merged174/c4492593; final116/110 target unfinished. Existing frame restoration was visiting EVERY logical source's SideBar and choosing first global CommsSidebar, including hidden sources. This duplicates hydration/restoration across tab count and can capture/restore the wrong source's reader. Move source-local preparation/scroll/capture into existing SessionView declaration, leave shared frame generation/geometry/tabbar with WorkspaceScreen. No source cache/pool, roster, codec, mode dispatch or compatibility introduced. First delete global source scans and wrong-first-sidebar reads; selected logical source supplies behavior.

Existing installed native cohort harness now uses physical tab clicks, records actual production select-session boundary to composited destination draft AND loaded native response. No fixed20ms settle added. Reports first-painted frame/observed frame tail, separate blank vs loaded records, normal GC/RSS/tasks/native ownership/queued delivery/editor state; cannot equate headless compositor with terminal writer latency. Two actual native saved-history owners remain fixed across4/16/32/64; other tabs are blank. This is provisional mixed-cohort scaling, not64 separately loaded native processes.

Initial4-tab diagnostic with cProfile is guidance only, not latency acceptance. Corrected real two-history unprofiled baseline running before installing production change. Whole4/16/32/64 changed candidate plus retained full continuous saved-state/idle/End/fork gate required; noCI/final50ms checkpoint hold. Parent owns export/live default, untouched here. Exact latest NRA/refactor-audit applies IDEN-1/IDEN-7/IMPL-10: source-local navigation work belongs selected declaration; screen owns geometry.

## Changed candidate provisional matrix PASS

Actual installed product91c68432 (consumer harness import correctiond86c6663), corec2aebdb3/Textual73909c04/native d396. Physical normal tab-click-to-first-compositor destination content (draft + native loaded answer) measurement; ordinary GC; fixed TWO actual loaded native histories, remainderblank, not all64 histories. Native held/queued2percohort delivered/painted, same originalAgent/process/editor/Document/EditHistory/undo retained, globalrichConversation1; processEXIT0.

| Tabs | Blank median ms | Loaded median ms | Worst ms | UI RSS bytes | >100ms switches |
|---|---:|---:|---:|---:|---:|
|4|49.31|173.11|195.18|156549120|5|
|16|50.67|195.43|207.62|164216832|5|
|32|58.40|219.06|236.25|172167168|5|
|64|74.49|232.44|242.19|183664640|5|

Baseline before selected-scope change4-tabs: blank49.94ms/loaded170.20ms/worst185.78ms. This does NOT establish a speedup; loading remains slow, target<50ms unfinished. Profiled diagnostic timings excluded: cProfile greatly changes elapsed times. Correct selected-source ownership removes O(alllogicalsidebars) restore/hydration and wrong-first-scroll capture, independently useful correctness/scaling closure. Profile identifies canonical source metadata/guard read and repeated saved-page publication/layout as remaining investigation; no weakened durability guard/cache or speculative alternatepager introduced. Final continuous same13/17/13 rendered-cache/zero-raw-read/idle/End/physicalfork/channel journey running after source-scope change.

Mechanical exactarchive ratchet: chain terms+0,foreign absence+0,weighted debt0 bothtouchedproductionfiles; allsourceownerclasses remainbelowgodthreshold500. Completed own174localbranch removed only after ancestry proven mergedmain; three completed scratchinstall/lock receipts deleted. Persistentpredecessors/live/evidence and runningprivatefixtures preserved.
