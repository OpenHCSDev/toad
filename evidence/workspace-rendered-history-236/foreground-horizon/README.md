# Foreground delivery owns the lookahead horizon

## Actual producer/consumer defect

DirectionalPreparation predicts travel over the measured foreground delivery
latency. DocumentViewport called `delivered` inside generic `_restore_body`,
which is used for visible delivery, offscreen retained bodies and speculative
worker-prepared neighbors. A cheap background restore erased the slow foreground
measurement and reduced the prediction horizon prematurely. The declared
foreground/background distinction already existed; no new policy is introduced.

The existing `_reconcile` visible-body caller now measures its actual restoration
including history-lock wait. Generic restoration and speculative batches do not
publish a foreground measurement. All three restore consumers were traced:
the retained/visible loop, speculative neighbor loop and existing resource pilot.
There is one production delivery consumer and no new flag, clock, cache, source
state or mirrored authority. IDEN-1 applies: foreground latency and cheap warm-up
cost answer different questions. New bodies implement their existing contract
without new consumer cases. The one-file per-function dispatch ratchet adds zero.

## Native source UI evidence

The existing cadence pilot now retires an actual visible Markdown body, holds
the actual window history lock for0.5s, and lets the existing viewport worker
restore it. It then worker-prepares/restores a cold offscreen Markdown body and
checks that the foreground measurement survives. Actual PageUp, idle, PageDown,
reverse and End still exercise native demand and the configured0.2s idle expiry.
No fake body/app/clock, provider, ACP process or original-root operation.

| Delivery horizon | Baseline | Candidate |
| --- | ---: | ---: |
| After visible restoration |534.316ms|520.571ms|
| After background warming |3.730ms|520.571ms|
| Outcome |overwritten, assertion FAIL|preserved, full pilot PASS|

Run against this checkout's source using the retained installed dependencies:

```sh
CADENCE_SCRATCH="$PWD/.artifacts/foreground-horizon-candidate-02" \
PYTHONPATH="$PWD/src:$PWD/tests" timeout 40 \
.artifacts/installed-warm-admission/bin/python tests/viewport_idle_cadence_pilot.py
```

First candidate stopped before the restoration phase because its observer sampled
visibility before native layout completed. Its log is preserved at
`.artifacts/foreground-horizon-candidate.log`. The existing pilot now physically
presses End and awaits an actual visible body before resource contention; the
successful02 gate retains that precondition. No assertion is weakened.

This proves the source-native body/worker/keyboard prediction contract. It is not
installed original41MB video acceptance, proof that preparation always leads the
visible edge, or closure of physical gaps, warm Strips, focus or full TC1/T9.
The useful trim checkpoint remains unchanged; both changes need the single
fresh matched-cohort physical comparison with Kepler before live readiness.
