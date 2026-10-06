# Sidebar refresh ownership

The collapse watcher changes the original sidebar visibility and layout. Textual style/display setters invalidate their native widgets; Widget._on_idle calls _check_refresh, which sends original Layout/Update/UpdateScroll messages to Screen. Screen coalesces those messages in its update timer.

The mouse toggle additionally walked every descendant of both sidebars, flushed their pending invalidations, repeated workspace sidebar layout, and directly scheduled the private screen timer. The keyboard toggle did not do this. This competing refresh orchestration is deleted; both input paths now use the original watcher and native refresh owner. Focus behavior is retained.

The existing refactor-audit Package parsed all 728 Toad src/tests/tools modules and all 710 selected Textual src/tests modules with zero omissions. Read the toggle callers, watcher, native Widget idle/refresh dispatch and Screen layout/timer consumers before the deletion.

Changed source compiles and diff check passes. No application run or latency improvement is claimed yet.

Remaining semantic issue: WorkspaceScreen pauses its entire update timer during transcript mutation, and ViewportPresentation.prepare refuses the complete compositor frame for any unready visible transcript body. Screen also retains after-refresh callbacks until that frame paints. Atomic transcript publication and body readiness are real requirements; the next owner refactor must preserve them while avoiding unrelated chrome blockage. Existing translucent-screen and history-mutation consumers must migrate coherently. No readiness exemption or replacement cache has been added.
