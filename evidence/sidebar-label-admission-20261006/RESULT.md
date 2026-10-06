# Sidebar label preparation

ThreadRowsWork now uses the existing model preparation lane. Deleted ThreadRowsRenderTask, which only performed the same detached-text preparation through the transcript renderer. Original captured Core ThreadPresentation, content identity, independent result delivery and shutdown remain unchanged. Textual Content remains a paint resource, not the status authority.

The actual prepared-bars App check passed: concurrent equal rows produce independent deliveries, changed unread labels update, latest tab roster wins, and labels never acquire the renderer. The existing 60-row reuse check passed: 16 requests, one miss, 15 hits, median worker-result delivery 1.09ms, maximum 3.9ms. These are not frame-time or live latency claims.

Initial fixture refusals are retained here: prepared-bars reached no App because its disposable bus lacked the original protocol marker; initialized it through messaging.initialize_private_initial_protocol. Reuse fixture called an outdated ThreadView.roster signature; migrated it to the existing views.thread_views owner rather than copying its activity acquisition. Neither refusal exercised the changed preparation path.

Full original Package parsed 288 production, 403 test and 40 tool modules with zero omissions. No deleted renderer-task consumers remain; preparation return expression is AST-identical. Four changed Python files compile. BEFORE.json and AFTER.json record source coverage. Installation and actual live latency verification remain outstanding.
