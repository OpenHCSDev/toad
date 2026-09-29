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
no-input-replay, and bounded preparation assertions remain. The subcall receipt
will locate the cost within the current owners before changing their behavior.

## Remaining decision

Run one serial controlled-provider two-history cohort on a reviewed paired
runtime when headroom allows. Diagnose the measured subcall, then change the
existing owner and rerun the same journey. Preserve the one rich Conversation,
preparation budgets, rendered-body reuse and native source lifetime. A useful
latency checkpoint can ship before the final speed target. The independent
16/32/64 loaded-history and terminal-writer matrix from #184 is a separate
resource acceptance boundary; the two-history return journey does not prove it.

The headroom guard currently returns warning status because 11.5 GiB of swap is
in use, so this checkpoint records no new native timing or installed activation
claim. The global installation is owned by the parent.
