# Persistent workspace selected-source navigation latency

Continuation from merged174/c4492593; final116/110 target unfinished. Existing frame restoration was visiting EVERY logical source's SideBar and also mixes the shared Channels roster's lifecycle into generic logical-source capture. This duplicates hydration/restoration across tab count and obscures shared versus source-local navigation custody. Move thread-local sidebar preparation into existing SessionView. WorkspaceChrome captures and restores the single shared Channels roster; frame generation/geometry/tabbar stay with WorkspaceScreen. Delete generic logical-source capture and both actual App/WorkspaceSessions callers. No source cache/pool, roster, codec, mode dispatch or compatibility introduced. First delete global source scans and wrong-first-sidebar reads; selected logical source supplies behavior.

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

Baseline before selected-scope change4-tabs: blank49.94ms/loaded170.20ms/worst185.78ms. This does NOT establish a speedup; loading remains slow, target<50ms unfinished. Profiled diagnostic timings excluded: cProfile greatly changes elapsed times. Correct selected-source ownership removes O(alllogicalsidebars) restore/hydration and generic-source/shared-roster capture coupling, independently useful correctness/scaling closure. Profile identifies canonical source metadata/guard read and repeated saved-page publication/layout as remaining investigation; no weakened durability guard/cache or speculative alternatepager introduced. Final continuous same13/17/13 rendered-cache/zero-raw-read/idle/End/physicalfork/channel journey running after source-scope change.

Mechanical exactarchive ratchet: chain terms+0,foreign absence+0,weighted debt0 bothtouchedproductionfiles; allsourceownerclasses remainbelowgodthreshold500. Completed own174localbranch removed only after ancestry proven mergedmain; three completed scratchinstall/lock receipts deleted. Persistentpredecessors/live/evidence and runningprivatefixtures preserved.

## Final ownership closure after caller audit

CommsSidebar is the ONE shared Channels roster, not one per tab. Retain its hydration/readiness/scroll restoration in WorkspaceChrome (actual chrome owner), capture immediately before changing shared binding. Delete SessionView.capture_navigation and BOTH App.select_session / WorkspaceSessions.select callers. SessionView reconciles only its own SideBar children; no global query across all inactive sources. WorkspaceScreen invokes both declared owners and owns geometry only. Actual final full saved-state journey running after correction; earlier matrix explicitly precedes this final shared-roster correction and is provisional, not exact-final performance proof.

## Final shared/source custody product and matrix

Productdaee0b73 finalscope installed native full continuous gate EXIT0: all13/17/13 actual visible MarkdownBlock/render-cache identities retained, raw0/0/0, idle64->64misses/3->3providerrequests/work[]/pending0 over1.2s, preparedbytes77983, actualvelocity/physicalEnd/reverse/recent-reader/draft/undo/forkfirstsend/channelreciprocalauthor pathPASS. No shared root or live route changes.

Same finalsource product provisional4/16/32/64 matrix EXIT0, fixedtwo genuinely loaded native histories and allotherblank tabs. This corrects the prior source-only matrix above by retaining sharedroster lifecycle underchrome:

|Tabs|Blank median ms|Loaded median ms|Worst ms|UI RSS bytes|
|---|---:|---:|---:|---:|
|4|56.05|162.89|189.99|157626368|
|16|51.05|189.67|199.13|165048320|
|32|60.11|213.85|247.25|170881024|
|64|74.83|239.59|276.82|180494336|

Native queue/reply2percohortPASS, originalsourceAgent/process/editor/Document/EditHistory/undo retained, globalrichConversation1; noGCdisable/forcedcollect/timingdeadlineinflation or fixed20ms addition. Frame tails recorded perclick in final-matrix.json. Target<50ms remains unmet. This is mixed-source/headless compositor provisional evidence, NOT64 independently loaded histories or terminalwriter latency. No established causal speedup versusbaseline4; selected-source/sharedowner closure is useful independently.

Continuation2e4c561e pins NEWmerged corebeaa8c94/Textual609b74bf/native d396. Full finalcontinuous native affectedpath running on those exported noneditable wheels. The matrix above used corec2aebdb3/Textual73909c04; bothcorecanonicalread/stylesheet products are merged, latercorechanges toprivate selected-input admission notclaimedtestedbythatmatrix. No unchangedmatrixrerun forunrelatedcorechanges; current pairednativejourney proves new input contract. ParentcurrentLIVEefcdf493/c449/609b alreadyshipped preceding174checkpoint.

Exact finalguards: touchedfiles chainterms+0, foreignabsence+0, weighteddebt0, product code net0 lines; Appgodexcess269->267, otherchangedowners below500. Source/localbar behavior is derived from widgets ownedbySessionView; sharedChannels isexactlyWorkspaceChrome.channels declaration. Deleted genericSessionView.capture_navigation andALL2actualcallers, globalsidebarwalk onactivation, generic queryfirstCommsSidebar fromframe/source. Mechanicalguard artifacts ratchet-final.json/god-excess-final.json. All3owncompletedfeaturelocalrefs deleted onlyafterverifiedmergedmain ancestry; archivedpredecessor/shared trees andpublishedproofkept.

## Ready coherent current-pin checkpoint

Final product2e4c561e +publishedmerged corebeaa8c94 +Textual609b74bf +natived396, allinstallednoneditable: fullcontinuous saved-state normalApp/Pilot/actualPi/ACP/controlprovider journey EXIT0. Native13/17/13 actualrender-cache/leafidentity, raw0/0/0, originaldraft/Document/EditHistory/undo/readeroffset/sourceAgent/custody preserved; unchanged1.2s idle assertionPASS, nopendingwork. Endvelocity/reverse/idle resourcebehavior, firstforkinput/paintedreply/channelworking/responded/reciprocalauthor notificationPASS. Exact stats recorded merged-pins-journey.txt; includes newer coreselected-admission contract not covered byoldermatrix. No paidproviders/reset/replay/CI/fullsuite/50mstargethold. Ready for parentreview/export/live affected-entry gate; defaultrootalreadyparentowns.

Shipping closure: source-owned SideBar preparations touchonlyselectedSessionView; sharedChannels roster capture/preparation/restore usesWorkspaceChrome.channels.roster; allgenericSessionView.capture_navigation callersdeleted. 35oldproduction linesdeleted/30added across5files beforepins. No newcache/store/Screenpool/codec/modecase. Debt terms/foreignabsence+0, Appgodexcess shrinks2 andallotherchangedclassesbelow500.

Remaining assigned116/110 latency isstill unfinished: true terminalwriter phase/matchedindependentlyloadedhistories and sourceactivation/nativepagepublication cost neednextlargeproducerclosure. Provisionalfixedtwo-native-history mixed4/16/32/64 table above ishonest baseline tochoosework, notperformancecompletion. Parent can ship sourceownershipcheckpoint withouttargethold.
