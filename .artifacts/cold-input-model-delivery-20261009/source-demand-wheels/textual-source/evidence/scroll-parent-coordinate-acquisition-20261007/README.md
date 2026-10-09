# Nested scrolling parent coordinates

Widget.scroll_to_widget now acquires the parent virtual_region_with_margin once
per scrolling step, after the parent's scroll_to_region call. Translation and
intersection derive from that same immutable Region. Previously each step read
the property twice, repeating Screen/Compositor lookup and margin growth.
The original first-read order, ancestor traversal, style access, dock admission,
scroll arguments, callback ownership and custom geometry property remain intact.
A custom property is still invoked; translation and clipping use its one answer.

Existing refactor-audit Package parsed all 249 production modules, zero omissions.
The complete consumer family is Screen focus scrolling, Widget focus/scroll
helpers, ListView, Markdown and RadioSet. All use the same unchanged method API.
The parent-coordinate read in this method drops from two sites to one. The
initial target acquisition remains independent.

Real nested App control passed (1 test, 0.35s): bordered/margined containers both
scroll, target ends visible through both, each parent getter called once.
The same application exercised App.run_async with original headless driver:
terminal 0, 42.29ms operation including Pilot's idle wait. This is correctness
and reduced lookup work, not a sidebar latency result or physical UI acceptance.
No provider, package, installed pin or public App operation.

First run_async driver attempt incorrectly awaited Pilot.pause from inside an
after-refresh callback. It produced no result and was stopped with SIGINT;
original process3491947 joined at exit0. Corrected driver signals readiness in
that callback and executes the scrolling check from its external controlling
coroutine; original App task is joined on exit. No native callback repair was
inferred from that driver error.

Tree resize was also traced: rebuilding remeasures get_label_width/render_label,
whose custom implementations can depend on viewport size. No resize invalidation
was removed. The reported 45ms reflow remains unqualified by this small change.
