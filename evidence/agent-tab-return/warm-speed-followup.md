# Native agent tab warm return: next measured slice

This follows merged #194 on current `main`. #116 is closed as a superseded
historical branch; draft #195 deletes its obsolete per-mode probe. #196 owns the
channel caller correction and installed channel-entry verification. This slice
uses the existing two-native-history A/B/A journey and does not change channel
or Conversation code while #196 is in flight.

## Starting measurement

The four retained #194 controlled-provider receipts in the owner's
`/home/ts/.cache/agent-scratch/toad-pr194-turn-20260929/` directory contain 20
physical agent-tab return selections. Each passed retained response identity and
zero preparation misses. Selection-to-first-displayable-paint was 154.0–199.2 ms
(median 175.4 ms). Nested phase timers show native retirement 22.9–39.0 ms
(median 31.0 ms), activation 82.2–99.0 ms (median 91.1 ms), and navigation
layout 11.8–18.2 ms (median 13.2 ms). Phase timers overlap their parent calls,
so they must not be summed with parent totals. Click-to-paint also includes
driver/click work and is not the same measure.

The existing `tests/native_loaded_return_cache_pilot.py` now measures the
retirement and activation subcalls on the same real UI/ACP/Pi path. Its original
first-frame source, reader, goal, turn, scroll, body identity, editor, process,
no-input-replay, and bounded preparation assertions remain.

The first source change replaces the viewport's full warm-body scan on each
fragment return with a direct lookup in its existing bounded ordered cache.
`FragmentPresentationIdentity` includes native-page position to distinguish
identical repeated fragments and hashes without assuming wire events are
hashable. Its full equality still rejects changed content, watcher and source
identity. Active bodies retain weak-reference keys; only parked fragments use
their native identity. The viewport still owns one cache and one eviction
budget. The duplicate fragment comparison after identity equality was removed.
The retained-body UI pilot now uses two equal saved events at distinct page
positions and requires each to reclaim its own original widget.

Snapshot and follow-tail checkpoint publication now submit
`TranscriptRenderTask` through the existing application `PreparationRuntime`.
Previously both sent the same saved events directly to the renderer on each
source return, bypassing its bounded reusable result. The native A/B/A pilot
now observes actual renderer submissions after both sources are established
and rejects any saved-page refragmentation during warm returns. A focused
source run with the real one-worker render pool submitted the same immutable
page twice, returned independent equal fragments, and measured one miss, one
hit, zero shared work and 2,180 retained bytes. This proves the preparation
route, not the still-pending native UI latency result.

The parent's actual large-history profile is read-only at
`/home/ts/.cache/agent-scratch/toad-pr194-turn-20260929/live-large-return.prof`.
It includes startup as well as A/B/A selection: 19.9 million calls/14.46 s,
with 73 workspace layout refreshes totaling 1.01 s and 2,085 stylesheet
applications totaling 0.86 s. Fragment construction totaled 0.016 s over 20
calls. These totals are **not selection-only** and do not show that indexing
alone resolves the live delay; the new phase receipt and actual large-history
selection remain necessary.

## Remaining decision

Run one serial controlled-provider two-history cohort on a reviewed paired
runtime when headroom allows. Diagnose the measured subcall, then change the
existing owner and rerun the same journey. Preserve the one rich Conversation,
preparation budgets, rendered-body reuse and native source lifetime. A useful
latency checkpoint can ship before the final speed target. The independent
16/32/64 loaded-history and terminal-writer matrix from #184 is a separate
resource acceptance boundary; the two-history return journey does not prove it.

The headroom guard currently returns warning status because 11.5 GiB of swap is
in use. One serial source-tree native run entered `ToadApp.run_test` but used a
CPU core for two minutes before a Pi child or A/B/A receipt; the owned process
was stopped. A bounded traceback retry located the pre-native loop in
`GoalBar._update_separators → _update_goal_text → GoalInteraction.members_with`.
The existing provider-free `retained_body_transfer_pilot.py` also spun before
its first paint and was stopped; it supplied no cache acceptance. Logs for
these owned failed attempts are in
`/home/ts/.cache/agent-scratch/toad-warm-return-followup-20260929/`.
That goal path belongs to the parent. The indexed-cache and preparation changes
have a passing direct canonical-identity lookup, real render-pool reuse, and
syntax/diff checks, but **no native
acceptance or speedup claim** yet. The global installation is owned by the
parent.
