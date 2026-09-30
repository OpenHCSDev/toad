# Attempt03: actual source movement and retained original return

Protected raw:
`/home/ts/.cache/agent-scratch/toad-workspace-warm-236-20260930-attempt03/capture`.
Source/pair remains Toad479e8783, Core4295d680, Textual2e49cb83, SDK0.12.1,
nativee36. No capture, provider call, native input, public owner restart or source
recopy was performed by this review. Heisenberg owns the actual fixture/run.

## Original source, not reflowed scroll coordinates

Actual native Window focus held throughout Up/Down/reverse. Saved history loaded;
the unsent draft remained `warm-scroll-draft`. The old observer incorrectly
compared numeric scroll signs across different mounted extents:

| Phase | Scroll/max | Oldest admitted native source offset |
| --- | --- | --- |
| Focused |108/108|41088858|
| Held PageUp done |163/542|40819442|
| Held PageDown done |109/170|41091275|
| Reverse PageUp done |100/240|40701070|

Prepending and trimming change the geometry coordinate system. The corrected
typed observation retains the page's original TranscriptCursor and delegates
ordering to its existing `contains` contract, with strict inequality. These
cursors certify older → newer → older source admission; there is no parallel
cursor, manually encoded identity or alternate comparison scheme. Counts now
count actual admitted pages, rather than TranscriptHistory widget instances.

Reprocessing the same immutable attempt02 snapshots still rejects its stopped,
empty-history journey. Attempt03 now passes original loaded history, extent,
native focus, source-direction, A/B/A selection, original editor/window/reader
and ready-body retention, draft and actual Ctrl+Z checks. Its **cold peer history
check remains failed**: b-open and return-a contain zero peer pages; a-return and
undo contain two peer pages loaded in the background. That does not prove a
readable peer first paint. Original failed raw receipts are unchanged. The new
native review is retained separately in this evidence directory.

## Same physical recording and CPU profile

Review artifacts:
`/home/ts/.cache/agent-scratch/kepler236-physical-review-20260930`.
Four message-area contact sheets sample the original video at5fps for Up, Down,
reverse and original return. Inspection shows readable content progressing through
those scroll phases; the original return transitions from the peer loading screen
to the retained original history. Exact phase PNGs Up/Down/idle also show readable
body and chrome, with End+15-second stationary observation at the original tail.
No complete blank viewport appears in those inspected samples. Sampling cannot
exclude a single33ms gap or certify smooth frame pacing.

| Same-run phase | Video interval (seconds) | UI CPU seconds | Average UI CPU |
| --- | --- | --- | --- |
| Up |23.491–29.169|4.65|81.9%|
| Down |30.553–36.299|4.57|79.5%|
| Reverse |37.680–43.333|4.72|83.5%|
| End stationary |47.376–63.881|1.65|10.0%|
| Return A |70.771–75.069|1.60|37.2%|

The profile has879 GIL samples, one reported sampling error, and nominal
video/trace alignment uncertainty±74ms. Down-phase sampled stacks include native
compositor chopping/arrangement and widget traversal; reverse includes compositor
add_widget and traversal. These are observed stack changes, **not** function CPU
time, call counts, or proof of a33ms visual cause. Kernel deltas provide measured
process CPU. Phase intervals include screenshot/DTO attachment and native target
helper overhead; initial repeated frames cannot be labeled a user scroll stall
without the actual injection boundary. No matched-source baseline performance
improvement or final50ms claim follows from these numbers.

The offline sheet generation reused existing ProcessOwner for four serial ffmpeg
processes, one decoder thread each. Cleanup reports no remaining owned PIDs or
errors; temporary retained-DTO review links were removed. The review directory
is owned by Kepler221 and retained as scoped proof for parent/Heisenberg review.
The original raw video, failure receipts and profile remain protected.

This supports a useful original-history buffer checkpoint, subject to the
integration owner's source review. It does not grant full warm-peer readiness,
mid-compaction switch readiness (Sch238), backend-delay closure (Mendel450), or
default activation. No new physical run is requested for this observer repair.
