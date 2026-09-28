# Consume nominal thread lifecycle owners

Paired with core172 and current views173. CommsSidebar no longer switches on ThreadStatus enum members: determining status owns active/native eligibility and context-control availability. Current ThreadView fixtures construct actual status declarations. No alias or compatibility enum remains.

Current mounted channel visibility (stopped/archived), main-menu export/import and right Comms group/navigation/mutual relation checks pass. Standalone right-Comms fixture was stale: it lacked current SidebarLayout/PreparationRuntime services and expected nested group scroll owners removed by the shared sidebar layout. It now uses the existing services with explicit teardown and asserts no nested group scrolling. Dedicated actual sidebar viewport coverage remains in sidebar_nonvirtual_scroll_pilot.py. Failed intermediate evidence retained; no production fallback added for fixtures.

Parent combined core85+2 current process cases and108 status/view boundary cases pass. Local source tests only; parent owns paired installation and live acceptance. CI deferred. Pin coref5ddd74 and latest merged Textual4fa6a9c.
