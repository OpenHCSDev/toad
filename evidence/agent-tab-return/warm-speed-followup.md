# Native agent tab warm return: next measured slice

This follows merged #194/#196 on current `main`. #116 is closed as a superseded
historical branch; draft #195 deletes its obsolete per-mode probe. This slice
uses the existing two-native-history A/B/A journey and leaves shared Conversation,
goal/turn and channel integration with the parent.

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
hit, zero shared work and 2,180 retained bytes.

## Paired source/UI receipt

The original attempts used `runtime-sidebar-20260929`, whose installed
`textual/reactive.py` differs from OpenHCSDev/Textual `412b5a2b`. This worktree
has no `.venv`. The later `runtime-turn-authority-20260929` interpreter has the
exact `412b5a2b` reactive file; it was used read-only with this PR's source and
the installed native Pi package `9213ee71479d1b20`.

The provider-free `retained_body_transfer_pilot.py` exited 0 after actual
Textual paint, tab return, and distinct original-widget reuse for two equal
saved events. The first paired run of `native_loaded_return_cache_pilot.py`
exited 0 through actual editor sends, controlled local provider, Pi, ACP,
physical A/B/A clicks, first-frame reader/goal/turn checks, scroll, draft/undo,
active-other-tab and settlement, with no input replay. Its five return receipts
are in the owned scratch directory as `native-paired.json`: every return had
three preparation hits, zero misses, a reused painted response, no retained-body
evictions, and no fresh transcript render submission. Median selection-to-first
paint was 186.3 ms (175.8–194.7 ms), native retirement 30.7 ms, activation
104.5 ms, and retained presentation 69.3 ms. This does **not** demonstrate a
speedup against the 175.4 ms pre-change median.

A second exit-0 run instrumented the inner return calls; `native-paired-phases.json`
records five more physical returns, median selection-to-paint 200.7 ms. Median
goal read was 46.9 ms and native page read 15.5 ms; these run concurrently.
Snapshot publication then took 32.4 ms, including 2.4 ms of preparation
submission, within a 66.6 ms retained-presentation phase. Phase times overlap
and are instrumentation/cohort-specific. Goal read and its source correctness
belong to the parent's #198; the remaining snapshot publication and viewport
cost remain in this PR's performance scope.

The parent's actual large-history profile is read-only at
`/home/ts/.cache/agent-scratch/toad-pr194-turn-20260929/live-large-return.prof`.
It includes startup as well as A/B/A selection: 19.9 million calls/14.46 s,
with 73 workspace layout refreshes totaling 1.01 s and 2,085 stylesheet
applications totaling 0.86 s. Fragment construction totaled 0.016 s over 20
calls. These totals are **not selection-only** and do not show that indexing
alone resolves the live delay; the new phase receipt and actual large-history
selection remain necessary.

## Remaining decision

Measure the parent's actual large-history A/B/A source with selection-only
timing, then reduce snapshot publication/viewport latency in their existing
owners. Preserve the one rich Conversation, preparation budgets, rendered-body
reuse and native source lifetime. This tested checkpoint can ship before the
final speed target. The independent
16/32/64 loaded-history and terminal-writer matrix from #184 is a separate
resource acceptance boundary; the two-history return journey does not prove it.

The headroom guard returns warning status because 11.5 GiB of swap is in use;
all paired runs were serial and bounded. The earlier pre-paint GoalBar loop on
the outdated Textual runtime is superseded by the paired receipts above. The
parent separately owns the no-goal ClientTurn/NoTurn equality fix and the live
sidebar geometry/lifecycle issue. This branch has **native source acceptance,
but no large-history live speedup claim**. The global installation is owned by
the parent.
