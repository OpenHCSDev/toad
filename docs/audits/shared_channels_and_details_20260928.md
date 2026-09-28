# Shared Channels and compact session details

Development base: merged Toad PR73 (`7a279b0`), with core `ab98c19` and Textual
`94e504dddb59f3fcfdcaab7b3954ed471b3c6120`. The development comparisons below retain
those exact identities. The final integrated dependency pair is recorded next.

## PR #108 landing integration

Textual #7 merged at **`16ede007c34bec893b2dbedb3999223381129678`**. Its tree
`096a8cbd411a62f9bf632194f4a2e4d02edd74d5` exactly equals the tested framework
feature head. This Toad branch now pins that merge and integrates current main
**`511a1a2` (#106)**, preserving saved-channel read-only history/composer behavior.

The integration smoke test exposed #106's dependency mismatch: its SavedView
provenance field is absent from the previous core `ab98c19` pin. The final core
pin is the minimal paired, already-merged core #231 revision
**`3996e820157b674f456974c1a8417de4776e1279`**. No unmerged L0A/core branches are
included. The new shared-panel fixture uses exact tag channels and actual member
tags; the full suite now includes #106's saved-channel retirement contract.

Validation on this exact source/pin combination:

- Four integration smoke cases: **4 passed in 27.42 s**.
- Complete **132 tests plus 73 subtests passed in 647.74 s**, including all final
  mouse-capture/status-order/ANSI fixes and the new saved-view test. Comms 59.88 s,
  peak 596.6 MiB, zero swap; the 100 s per-pilot limit is unchanged.
- `toad-pr108-landing-navigation`: **83 actions / 10 tabs / 8 resizes**; one widget
  ID per channel across every mode, no replaced observed channel rows. Peak
  507.3 MiB, zero swap.
- `toad-pr108-landing-filters`: **72 actions, all seven categories, all four
  restored masks/drafts, 52/52 input markers**. Input acknowledgment median/p95/max
  **33.23/57.57/73.53 ms**; maximum loop gap **144.75 ms**, GC **72.95 ms**. Peak
  480.5 MiB, zero swap. These receipts still do not establish universal sub-50-ms
  latency; the earlier adverse measurements remain in this audit.
- Offline replay's last retired `set_channel` call now uses the exact-tag API.
  A disposable current-declaration capture completed all eight replay/filter
  actions with draft checks. Partial saved-view captures are explicitly rejected
  instead of synthesized as writable targets; matching capture/declaration
  revisions are required. No private user capture was used for this check.
- Scoped Ruff and diff checks pass. Tests/captures ran serially with 4 GiB/no-swap
  caps; owned capture scopes were stopped after recording memory peaks.

All package changes above are source pins and isolated validation. Core #231's
existing quiet catalog-cutover requirement remains with the installation owner,
as documented in `evidence/channel-deletion/HANDOFF.md`. No shared stack, live
catalog, installed application, or running user preview was changed here.

## Ownership correction

The previous fix retained each tab's Channels rows. That prevented warm-revisit
flicker but still duplicated the global navigation tree and rebuilt it for new
tabs. Channels is now **one application-owned panel and one native row tree**.
Each session/loading/channel view declares only a hidden `ChannelsSlot` locating
that shared presentation. Thread-specific panels remain owned by their tabs.

Before switching the native mode, the app transfers the existing panel through
`Widget.reparent`. Rows, message pumps, timers, scroll state and cached paint
survive. The destination is bound through polymorphic `channels_context` methods;
it does not reconstruct the channel source or dispatch by class-name strings.
Slotless views park the panel without polling. Closing a tab does not destroy
global navigation; application shutdown does.

Actual route replacement still hides old information. The app's validated
`coordination_wire` owns source identity; a changed service retires its old cached
projection. Async reads and publications carry that service identity and discard
old results after rebinding. A same-named thread on another root cannot borrow an
old-root open view. Row preparation recomputes live mode routes after awaiting;
late results cannot restore a closed tab's navigation target.

An awaiting transfer rechecks the destination against the native mode stack
before moving custody. A closed destination cancels the transition. A channel
conversation finishing hydration after the user leaves binds only its own
content, not whichever tab now owns Channels. Both races have deterministic
fail-before regressions (NoMatches during late hydration; WidgetError during a
closed-mode transfer). Native initialization may queue an early ScreenResume;
mount/resume hooks tolerate the empty slot until selection transfers the panel.
Navigation during a sidebar drag releases native mouse capture before transfer;
resize/slider controls handle MouseRelease by ending their gesture. A held-edge
regression fails before this correction, rather than masking the framework's
capture guard or moving a still-captured subtree.

The right-hand Thread panel stays independent. Code that means Channels now
selects `#channels-sidebar`, rather than relying on which `SideBar` happens to
occur first in DOM order.

## Session details disclosure

The screenshot supplied by the user showed roughly twelve lines of accumulated
recent messages, bus-history status and notice counts above the composer. These
now live inside one `SessionDetails` disclosure:

- Collapsed by default, with a one-line status/count summary.
- Explicit “Needs attention” and warning styling for unavailable/unconfirmed data.
- Expanded content is scrollable and bounded by the configurable `DETAIL_ROWS`
  class policy (default eight content rows).
- Existing observation, native-history and delivery widgets remain the data
  owners; no receipt, read, retry or delivery semantics were changed.
- Delivery Inspect opens the same session-details context, including the recent
  observations and bus-history overview alongside current/historical notices.
- Empty details disappear; active-turn feedback, goals and the composer retain
  their own roles.

The user subsequently reported the separator occupying the former live-status
position. `TurnActivity` now precedes SessionDetails, preserving the visible
Thinking / Writing response / Calling tool row above metadata. The disclosure's
border-free rule explicitly covers `:ansi`; the inherited ANSI Collapsible border
otherwise reappeared after theme/CSS resolution. Regression checks reproduce both
the wrong order and the extra border before their corrections, then verify the
actual painted status row with collapsed/expanded details at two terminal sizes,
RGB and ANSI color, busy animation and an unchanged draft. No activity-source or
turn-state logic was replaced.

## Verification and limits

- Textual's five new transfer cases cover widget/task identity, native ancestry
  and styles, cross-screen selection/focus, old-scene cleanup, invalid moves,
  pending frame callbacks and mouse capture. The initial three fail before the
  API existed. **3,512 framework tests pass**, 1 skip, 4 xfail, in 200.77 s,
  peak 250.8 MiB and zero swap.
- The shared Channels pilot verifies the same panel/rows/tasks across new empty,
  loading, thread, channel and warm tabs; a populated roster on every observed
  frame; unchanged cached header paint; independent right panels; close cleanup;
  and a gated old-root read released after replacement.
- The session-details pilot supplies 30 long notifications and 5 cleared notices,
  verifies one collapsed row, bounded expansion, visible bus-history details,
  attention indication, and unchanged source/draft state. The owner pilot verifies
  that the real inspector receives the same overview as the inline disclosure.
- The full Toad repeat passes **131 tests plus 73 subtests in 626.68 s**, including
  late hydration and cancelled-transfer regressions. Comms takes 59.63 s; peak
  memory 595.3 MiB, zero swap. The original 100 s per-pilot deadline is unchanged.
  An earlier full run's generic SideBar selector failure was corrected explicitly,
  then verified by 21 focused cases and this complete repeat.
- The held-drag follow-up was added after the full run; its release correction is
  checked separately by **13 focused pilots in 132.94 s** (comms 57.07 s, peak
  528.1 MiB) and native captures. The later status-order/ANSI correction passes its
  expanded pilot in **5.15 s**, with nine related activity, cursor, delivery, goal
  and throbber cases also passing. An initial test used an unregistered theme name;
  the corrected test uses the supported `ansi_color` setting and stylesheet refresh.
- Native `toad-shared-native-navigation` completes **83 actions / 10 tabs / 8 resizes**.
  All four channel identities are **singletons across all ten modes**, not merely
  stable copies within each mode. Scope peak 508.8 MiB, zero swap; owned scope stopped.
- A ten-tab headless run with 8 peers / 2 channels has zero replaced thread rows across
  three passes. Switch median/max 44.81/49.38 ms on first revisits, 37.31/38.17 ms and
  36.60/38.20 ms on later passes. This still performs 3–4 native reflows per switch;
  the change does not claim zero repaint or a universal latency target. Geometry,
  theme and selection changes remain valid reasons to redraw.

## Same-environment native comparison

`toad-shared-paired-baseline` uses merged Toad `7a279b0`; `toad-shared-paired-final`
uses the final feature source including the status-order/ANSI correction. Both
select the same Textual `94e504dd`, core `ab98c19`, CPython 3.14.2 build, diagnostic
driver, fixture hash and 83-action sequence. This is one serial pair, not a
statistical latency claim. Both complete ten tabs and eight resize gestures.

| Measurement | Merged baseline | Shared panel |
| --- | ---: | ---: |
| Distinct widget IDs per channel across ten modes | 10 | 1 |
| Live inactive sidebar widgets / message pumps | 1,018 | 383 |
| Live active sidebar widgets | 146 | 146 |
| Tracked objects at closing census | 545,655 | 498,868 |
| Scope peak memory | 519.4 MiB | 504.2 MiB |
| Switch-to-flush median / max | 94.20 / 166.68 ms | 89.87 / 132.36 ms |
| New-tab feedback flush median / max | 51.11 / 86.33 ms | 99.49 / 109.78 ms |
| Final session-shell flush median / max | 296.42 / 461.02 ms | 286.36 / 429.25 ms |
| Content-ready handler median / max | 778.19 / 950.53 ms | 698.69 / 857.03 ms |

The ownership reduction is clear: 635 fewer inactive sidebar widgets and message
pumps, with all channel rows truly shared. Early loading feedback is slower in
this pair; transferring the populated panel still incurs native ancestry/style/
layout work. This change does not meet the universal sub-50-ms target or justify
claiming every operation renders faster. Census values are observed live objects,
not transitive retained-heap or leak proofs.

Final `toad-shared-status-final-filters` completes **72 actions**, all seven filter
categories, all four restored masks/drafts and **52/52 input markers**. Input
acknowledgment median/p95/max is **29.11/50.07/68.40 ms**; maximum loop gap **136.26
ms**, maximum GC **63.55 ms**, peak memory 476.3 MiB, zero swap. Earlier same-branch
filter capture recorded input max 101.01 ms; the later run does not erase that
tail. All owned native scopes were stopped after recording their memory peaks.

All automated runs are serial, one pytest worker, with 4 GiB/no-swap caps. Private
live-window screenshots stay outside Git. The user-requested development preview
was launched separately from source, with exact module paths recorded locally;
the existing user window/draft and shared installed stack were not replaced.
Some final selector/custody fixes were made after that preview process started;
a later launch is needed to load those revisions. Do not silently restart a
preview in which the user may now have an unsent draft.
