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
