# PR213 canonical reader geometry checkpoint

Normal main43949 merge: 2d204ae8. No global mutation or native/provider call.

## Actual counterevidence and result

The same `reader_geometry_pilot.py` runs the real ToadApp, actual TranscriptHistory,
worker preparation, viewport/layout/compositor and native scroll bindings. It
mounts eight typed saved transcript records, scrolls with Home/Down, resizes the
real terminal viewport, then presses PageDown, PageUp, End and remains stationary.
It retains every completed display's text and scroll policy. This is a source UI
and installed baseline experiment, not a native ACP journey or physical video.

Installed baseline (read-only runtime-retained-native-history-20260929):
Toad43949eeccf5e92ed65920e0e9b85067c0aa96783, Coreab3397a6faaec148418dc82c87db4f02bd943a36,
Textual412b5a2b5da8875dc2f3dc5be2365abddce0537b, official ACP SDK0.12.1.
`PYTHONPATH=tests` imports installed production, not this worktree's source.
FAIL exit1: offset67/max77/followFalse becomes offset67/max67/followTrue after
resize with no scroll input. Expanding geometry then paints offset77/max77,
losing the reader. The journey continues through reverse, End and stationary
before failing its accumulated violations; none are waived. PageDown at the
already displaced bottom also releases follow without movement on this baseline.

Candidate: `PYTHONPATH=src:tests`, the same read-only paired interpreter.
PASS exit0: geometry meets the reader without changing follow; expansion keeps
offset67/max77/followFalse. Physical Pilot PageDown rejoins at77, PageUp releases,
End follows, and stationary paint is unchanged. The existing actual transcript
and IRC prepend/eviction/concurrent-input frame journey also exits0.

The earlier retained-return experiment posted saved history in an agentless
blank tab; Native.activate dereferenced that missing Agent. It was not reader
acceptance and its failure remains in owned scratch. The current counterevidence
does not use that malformed native tab fixture or claim physical A/B/A coverage.

## Ownership and deletion

Native `_anchored` / `_anchor_released` remain the sole follow authority. The
HistoryWindow watcher accepts automatic rejoining after actual downward movement;
the existing WindowRestoration transaction excludes compensated movements.
Geometry-only `_check_anchor` is no longer allowed to choose follow, and
`check_follow` only applies the policy. Explicit End/anchor remains valid.
No released-state copy, new flag, polling, restore retry or second reader store.

SnapshotPublication deletes its unconditional anchor writer and inherits the
same policy. Its sole prepare_reader consumer no longer asks a boolean question;
prepare_reader only applies the existing eviction-owned ReaderPosition resource.
Snapshot source/generation/frontier/coverage validation is unchanged. Schrodinger
handed off these reader-policy methods; his source-operation methods stay owned.

All check_follow consumers (DocumentViewport frame preparation, TranscriptHistory
page publication and MountedMessageHistory page admission) inherit this owner.
TailAnchor/RecordAnchor and OffsetReaderPosition use the existing restoration
transaction; no consumer gets its own geometry/follow condition.

This checkpoint deletes13 production lines and adds13 in two files. Prior213
owned-resource close deleted6/add4 in session_presentation.py. No new family,
registry, compatibility reader or dispatcher. A new scroll-input path needs zero
HistoryWindow consumer roster edits: it inherits the native position watcher.

Latest authoritative NRA/refactor-audit archive reviewed: IDEN-1/3/5, IMPL-1/4/
10/12/14, TIME-1 through9. The bounded before/after census covers only these two
files and their functions, no global scan. StringDispatch/TypeSwitch and arms
remain0 at both levels; foreign-absence and boolean-chain measures do not grow.
This is not full TC1 completion.

## Commands and boundaries

```
timeout --signal=TERM --kill-after=5s 40s env PYTHONPATH=tests \
 TMPDIR=$PWD/.artifacts/reader-geometry \
 READER_GEOMETRY_EVIDENCE=$PWD/.artifacts/reader-geometry/installed-baseline-complete \
 /home/ts/.local/share/agent-comms/runtime-retained-native-history-20260929/bin/python \
 -B -u tests/reader_geometry_pilot.py
```

Candidate changes only PYTHONPATH to `src:tests` and its evidence directory to
`source-candidate-complete`. The actual history compensation journey:

```
timeout --signal=TERM --kill-after=5s 40s env PYTHONPATH=src:tests \
 TMPDIR=$PWD/.artifacts/reader-geometry \
 .artifacts/current-pair-package/runtime/bin/python -B -u tests/history_scroll_frames_pilot.py
```

Both interpreters have Coreab/Textual412/SDK12.1. All fixture wire/config/state is
private under this WT's TemporaryDirectory and removed through ordinary teardown.
No live-root ensure_owner/start, global package writes or uncertain input replay.
Resource check: home20.2GiB/RAM12.6GiB; swap12.2GiB warning. One bounded UI serially,
no fleet, native process or provider response. Scratch owner Heisenberg, purpose
geometry counterevidence, `.artifacts/reader-geometry` (<1MiB before receipts).

Installed candidate read-only actual native A/B/A/lazy PageDown/reverse/idle/End
subsequently passed351 completed frames; see [READY](READY.md). The reproduced
geometry mechanism is real, but this source receipt does not prove it was the
exact caller in the earlier intermittent208 run.
Full large-history video/CPU, editor active/post-cancel keys and same-open-view
recovery remain PR213 work. No final50ms target or full TC1 gate on this checkpoint.
