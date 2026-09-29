# Native snapshot return latency follow-up

This branch stacks on draft #197 and leaves Conversation, goal/turn state, and
global installation with the parent. All source UI runs used paired Textual
`412b5a2b`, the installed native Pi package `9213ee71479d1b20`, and a
controlled local provider. The resource guard warned about swap, so runs were
serial and bounded.

The #197 five-return cohort measured median selection-to-first-paint 186.3 ms;
a second subphase cohort measured 200.7 ms. In the latter, median snapshot
publication was 32.4 ms and viewport parking 24.3 ms. A selection-only
`cProfile` run passed the same native A/B/A journey, but profiling more than
doubled wall times. A separate provider-free profile found the retained page
admission called `Widget.reparent` for each saved body, and `reparent` already
refreshes its old and new parents. `TranscriptPageView.admit_retained` then
refreshed each moved body again; that redundant refresh was removed. A claimed
body now skips reapplying an unchanged category filter, while a changed
selection still applies normally.

The current five-return native cohort exited 0 with the existing first-frame
reader/goal/turn, editor/undo, active-other-tab, settlement, no-replay, body
reuse, and bounded preparation checks. All returns again had zero preparation
misses and reused a painted response. Median selection-to-first-paint was
185.3 ms, snapshot publication 30.6 ms, and viewport parking 22.6 ms. These
small cohorts do **not** establish a speedup; the final target and actual
large-history selection remain open.

A placement experiment moved retained bodies into each session's existing
hidden slot and passed the native journey, but its median selection-to-paint
was 195.9 ms and it did not reduce the measured parking/publication phases.
That code was discarded. The saved-history duplicate-body fixture was also
corrected in #197: it now uses a project directory separate from generated
wire/config/state data, so its directory watcher revision stays stable.

## Complete page transfer checkpoint

A phase probe on the five-return native path found `TranscriptPageView` body
admission at median 26.8 ms of 33.3 ms snapshot publication; preparation
submission was 1.9 ms. The viewport now parks a fully admitted page as one
mounted subtree when all its bodies are in the same bounded warm set. A return
claims that page only when its source page, prepared fragments, admitted range,
category selection, and each fragment identity still match. It uses the same
warm cache and eviction budget. Partial or changed pages use the existing
fragment admission, and an interrupted claim releases its warm lookup keys.

The provider-free Textual pilot exited 0 for whole-page object reuse, paint,
and a rewritten-row return that reused only the unchanged bodies. The native
Pi/ACP pilot exited 0 with five physical A/B/A returns: all reclaimed one
original page object, reused painted response bodies, had zero preparation
misses, and passed reader, editor/undo, turn/goal, settlement and no-replay
checks. In that cohort, median snapshot publication was 27.2 ms and
selection-to-first-paint 181.4 ms, versus 33.3 ms and 181.9 ms in the earlier
instrumented cohort. It demonstrates page reuse and a shorter publication
phase in a small cohort, **not** a reliable first-paint improvement. This still
mounts a new outer history and reads the owner before first paint. Retaining
that outer presentation is the next source-lifecycle change to evaluate.

## Selection to actual display

The `native-first-frame-trace.json` receipt instruments five more physical
A/B/A selections through the actual Textual compositor and `_display` call.
Its median selection-to-first-completed-display was 195.2 ms. Nested medians
were 98.8 ms destination native activation (including native page and goal
reads plus 27.6 ms snapshot publication), 16.6 ms screen layout, 12.7 ms
compositor reflow within layout, and 9.9 ms compositor render update. The
departure's viewport park was 17.5 ms within native retirement. These phases
overlap and must not be added together. One return had a 127 ms layout outlier;
the measured compositor reflow inside it stayed 12.7 ms, so its remaining
delay needs a separate event-loop trace.

Textual already retains each widget's `_render_cache` of content `Strip` lines
and its `StylesCache` of styled lines. Across this first-display trace there
were median 19 content rasterizations (1.6 ms total) and 78 styled-line cache
misses (3.2 ms total); the selected screen's `render_update` still composed
the visible strips. Those figures are far smaller than source activation and
snapshot publication on this fixture. The controlled-provider renderer
received no saved-page work on warm return. Retaining a parallel bitmap or
strip store has no measured case here; retaining the existing outer mounted
history may bypass the owner read and publication before first paint.

All completed destination frames in this receipt contained the correct reader
and response, with no blank, loading, or other-source frame. Later frames had
a shorter visible reader than the first in each click. A terminal recording
is needed to determine whether that is an objectionable scroll correction;
the frame classification alone does not prove visually stable paint.
