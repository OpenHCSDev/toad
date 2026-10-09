# App owns frame cadence

Existing App.MAX_FPS now decodes TEXTUAL_FPS once through original environment codec, default144Hz; App subclass can override the declaration. App.frame_interval derives1/MAX_FPS. Animator consumes it instead of independently defaulting60; Screen update/selection movement+timer consume it instead of module UPDATE_PERIOD/constants.MAX_FPS. Delete old globalconstant and copiedperiod. Toad CLI120 import-time environment policy is deleted; Throbber derives original app period unless its caller supplies a genuine explicit refresh_interval override. Existing sidebar spinner setting remains independent and unchanged.

Native LoadingIndicator16Hz and indeterminateBar15Hz are their existing feature-specific visual sampling intervals, not declarations of the app frame cap; header/ETA1s, CSSmonitor.25s, cursorblink and game-clock ticks likewise retain their own meanings. No blanket144 replacement of unrelated timers. Frame target is not measured terminalFPS or a performancegain.

Existing refactor-audit Package.load:249native+287Toad+2diffviewmodules,0parse omissions. Original rate declarations/reads19native+15Toad; no diffview cadence use. Production Animator factory is only App, and all Screen/Throbber references to deletedperiod/rate are migrated. Tests using deleted UPDATE_PERIOD now read actualApp.frame_interval. External/privateAPI users beyond declaredroots are not proven by AST.

Throbber nullable refresh_interval is an optional explicitconfiguration override, not busy/lifecycle state; absent override derives App directly, no cached selected rate. Original mounted/busy/committedvisibility timer custody is preserved. SidebarProjection config cadence remains its originalsetting. No newtimer/scheduler/cache/clock class, alias or framework.

Source batch WIP published before final batchedsanity/changed installedpath. Current37film is frozen and does NOT qualify this cadence; no claim delivered144Hz, smoothermotion or improvedCPU. Full source/consumer/lifetime performance scope remains active.

Final native batch:40 animation, scrolling-animation, selection and timer deadline/lifetime checks passed in8.23s. These cover continued animation/selection speed and timer disposal, not terminalFPS. TIME-7 default copies are deleted; a new app cadence changes one original App declaration or its explicit override, not three60/120 constants. Installed changed-body/warm/input/motion validation remains outstanding.
