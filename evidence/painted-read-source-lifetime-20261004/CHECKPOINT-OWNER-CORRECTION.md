# Checkpoint decision ownership

The normal-main441 ratchet for `b5ca0f8092de350c625737701f4bd329c5ad027f`
failed on one positive: `ForeignAbsenceProbe` in `transcript_state.py`. The
original run37236476663 and its raw failed log are retained. No threshold or
waiver changes are involved.

Semantic reading found the complete checkpoint family has two source leaves:
saved `TranscriptHistory` and wire `MountedMessageHistory`. Both previously
recombined observed source admission with their own original resource readiness.
Live's read fence then asked the history facade for that combined decision.

`TranscriptState.checkpoint_available(owner)` now owns that source admission
decision, using its existing `accepts_source_work` declaration and the leaf's
original resource capability. `TranscriptSourcePreparation.checkpoint_available`
is the common facade delegating to the observed state. Both leaf checkpoint
implementations are replaced by `source_checkpoint_available`: saved history
still uses its existing filter checkpoint; wire history still requires its
original reader and non-loading source. Live's read fence calls its owned
checkpoint behavior.

This deletes the two leaf admission decisions and the foreign facade probe.
It introduces no checkpoint field, copied state, registry or alternate filter.
Working, provisional and suspended states still decline checkpoints through
their existing admission declaration. Pruning/closing observation and projected
source membership remain the original state classification. Filter scanning,
projection checkpoint, tail demand and all App/sidebar read guards are unchanged.

`checkpoint-owner-before.json` records all288 Toad,394 test,41 tool and249
native modules with zero parse omissions. The full source/decision family was
read; lexical evidence cannot prove external dynamic overrides or runtime.

The original single joined App at031/4406 remains qualified at its actual scope,
with all17 original Ready keeper hashes preserved. This corrected source changes
four production files and is not byte-equal to the previously installed8acfb
wheel. No App, build, package or native operation is authorized or performed by
this correction. The same existing control already exercises Live checkpoints,
filter scanning, Working and revoked scenes; wire-reader checkpoint behavior is
also part of the migrated source contract. Runtime qualification of the changed
bytes is separate from the original App receipt. Required ratchet and source
closure are reported for the exact corrected head.
