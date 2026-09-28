# R6 paired Toad — complete current callers

Pascal source `38b779984727561bddfe7e0a2983b51b710420a7`, branch `codex/refactor-r6-transcript-consumers-20260928`, persistent tree `~/wt/toad-refactor-r6-transcripts-20260928`. Reconciled main97 `884bba4`, preserving delivery/native attribution fixture changes and core pin. This PR intentionally leaves parent-owned pin/lock update for combined integration with core branch `codex/refactor-r6-transcripts-20260928` (source67e1974; receipt9ef2c09).

Production closure: TranscriptBlockConsumer/TranscriptCategoryConsumer/TranscriptFragmentConsumer dispatch by shared declaration MRO; no string event kind rosters. Concrete types own live text/activity/routing facts; budget uses text_size. Streaming Markdown/Thought select declarations directly. ACP decodes the complete current TranscriptPage through TranscriptCodec, including derived cursor fields; removed missing-page old-client fallback. All current fixtures/imports use those owners. Removed is_routed_event/TRANSCRIPT_ROLE/TranscriptEvent constructor and to_wire/from_wire aliases; tool starts no longer carry fictional text and assistant facts have no tool fields. Core owns saved parsing; UI creates no native reader/index.

Local receipts, existing installed dependency environment with source core/Toad mounted:
- process-second.log: actual separate render process,1217 exact fragments; stale/cancelled/detached and scroll-intent checks passed. No foreground parser blocking.
- tool-diff.log: mounted live/replay edit diff colors/hunks/line positions and bounded expansion passed.
- categories.log: all7 live/saved categories, selection UI, per-tab draft and read boundary passed.
- context-page-boundary.log: actual ACP snapshot decoder plus lazy original context/JSON/Markdown/user quote preservation passed.
- native-message-page-boundary.log: actual ACP snapshot decoder, combined adjacent assistant Markdown/list/fence with one timestamp passed.

Earlier process/context failures are retained; fixed imports/indentation and all current snapshot fixtures. Context/message-parts were rerun after final complete-page decoding. Main97 merge was fixture/pin-only, not a competing renderer change. No optional broad retesting or paid provider call.

Command in this tree:
`PYTHONPATH=src:/home/ts/wt/comms-refactor-r6-transcripts-20260928/src TMPDIR=/home/ts/wt/.r6-test timeout 60 /home/ts/.local/share/agent-comms/runtime-r1-pi-payloads-20260928/bin/python tests/<pilot>.py`

Core HANDOFF owns full source/testing/deletion map. Parent independently performs copied-root installed/mounted history, route preservation, paired pin and idle serial activation. This receipt claims local source behavior, not installed R6. No live root or runtime changed.

Exact source/test changed list is CHANGED-FILES.txt. Owned exited fixture/cache cleanup only; persistent tree and evidence retained.
