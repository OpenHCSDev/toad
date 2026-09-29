# Authentic recursion root: viewport layout reentry

Base main148b5a40ce4, own persistent ~/wt/toad-viewport-layout-reentry-sol-20260928. Parent deployment/source review; Tesla142 cedes minimal viewport site, continues workspace. No App/session_view/core edits.

## Authentic evidence supplied by owner

User terminal RecursionError on runtime-native-tool-owners/core3228ad/Toad9830/Textualc974: ViewportPresentation.prepare viewport_body80/83 -> window.check_follow -> screen._refresh_layout(scroll=True) -> SessionView._refresh_layout203 (no anchors) -> Textual Screen._refresh_layout1412 -> _compositor_refresh -> prepare again. MainScreen session-2,139x25. Rich fatal rendering then fails on exhausted stack. This is authentic user-supplied evidence, not a locally recovered full traceback. PR148 only captures errors; it did not fix this root.

## Semantic correction and deletion

Delete prepare's synchronous _refresh_layout call. HistoryWindow.check_follow already uses native _scroll_to; scroll_y watcher invokes _refresh_scroll, which queues native UpdateScroll on idle. That native scroll transaction owns the next reflow. Preparation returns False to avoid stale geometry paint while update is pending. No parallel scheduler, pending flags, reentrancy guard, global catch, or recursionlimit. Ownership remains ViewportPresentation and Textual's existing scroll lifecycle.

Latest2216 NRA/refactor-audit applied: IMPL-12 duplicate native reflow deleted, AGENT-8 actual installed test, IMPL-10 lifecycle scheduling owned by existing native transaction, TIME-9 no adapter. No chain introduced (terms unchanged), no product class grows. Both agent and channel SessionView callers consume same prepare API; no alternate path or caller alias.

## Actual installed evidence

Baseline installed native-tool-owners139x25 red: real ToadApp/HistoryWindow callback observing actual preparation+layout reported1 synchronous nested layout and preparation depth2. No fake check_follow/layout, no suppressed behavior. This reproduces reentry; it does not independently reproduce full exhausted-stack user crash.

Noneditable corrected wheel with same core3228ad/Textualc974 green: preparation depth1/no nested layout; real AgentResponse growth+resize70x25/139x25/139x26; automatic tail, reader scroll position preserved on growth, appended text actually painted in cropped Window; actual new session and original return, no app exception. Real ordinary ToadApp (not owner-stopping runtime_fixture), private root only, no prompts.

Installed physical Pi private loopback native send/source-return gate PASS exit0: native consumption, checkpoint source+paint, cold reattach, DM/channel, stopped owner reopen, actual ACP cleanup; idle zero model requests. Complete canonical paired native/core launchers supplied in owned environment; no earlier missing-launcher setup. No user input replay/live owners/history/launchers changed. Parent owns merge/install.
