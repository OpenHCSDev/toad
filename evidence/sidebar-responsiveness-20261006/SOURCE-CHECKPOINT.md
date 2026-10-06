# Sidebar refresh ownership

The collapse watcher changes the original sidebar visibility and layout. Textual style/display setters invalidate their native widgets; Widget._on_idle calls _check_refresh, which sends original Layout/Update/UpdateScroll messages to Screen. Screen coalesces those messages in its update timer.

The mouse toggle additionally walked every descendant of both sidebars, flushed their pending invalidations, repeated workspace sidebar layout, and directly scheduled the private screen timer. The keyboard toggle did not do this. This competing refresh orchestration is deleted; both input paths now use the original watcher and native refresh owner. Focus behavior is retained.

The existing refactor-audit Package parsed all 728 Toad src/tests/tools modules and all 710 selected Textual src/tests modules with zero omissions. Read the toggle callers, watcher, native Widget idle/refresh dispatch and Screen layout/timer consumers before the deletion.

Changed source compiles and diff check passes. No application run or latency improvement is claimed yet.

Remaining semantic issue: WorkspaceScreen pauses its entire update timer during transcript mutation, and ViewportPresentation.prepare refuses the complete compositor frame for any unready visible transcript body. Screen also retains after-refresh callbacks until that frame paints. Atomic transcript publication and body readiness are real requirements; the next owner refactor must preserve them while avoiding unrelated chrome blockage. Existing translucent-screen and history-mutation consumers must migrate coherently. No readiness exemption or replacement cache has been added.

ContextExplorer also built the full recorded-request/working-memory projection synchronously inside native presentation. ContextInspection.working_memory traverses recorded requests, every contributor segment and stored annotations. This pure model work now runs through the existing Coordination worker; HoldingInspection/NativeInspection still select groups polymorphically, and only the actual native Tree reconciliation runs on the UI loop. The original exclusive Textual worker owns cancellation and the acquired state identity prevents an obsolete projection from publishing after source replacement. No second context store or copied source reader was added. Runtime verification remains pending.

## Actual source App checkpoint

The original sidebar_collapse_latency_pilot ran through the actual Toad/Textual App with pointer-style toggles, ten mounted tabs and twelve authored transcript bodies (657 active widgets). The original fixture omitted its project thread; current strict target lookup logged UnregisteredThreadError even though the benchmark exited zero. That original log is retained. The fixture now declares its actual project target before opening the App. The corrected run joined and exited zero with empty stderr: left median55.4/p9565.9/max91.1ms; right median184.5/p95429.5/max438.5ms. This is a completed headless native _display boundary, not terminal pixels or the user's saved session. It demonstrates remaining right-sidebar latency; it does not establish an improvement or qualify the fix.

Owned receipts: /home/ts/.cache/agent-scratch/parent-sidebar-source-20261006/{collapse.stdout,collapse.stderr,collapse-fixed.stdout,collapse-fixed.stderr}. Original temporary authored wires were cleaned by the existing fixture after joined shutdown. No installed package was modified, configured provider/input used, or native SDK launched. The check used host Python with source roots and existing dependency files.
