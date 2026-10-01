# Guarded g458h/u02: actual emitted duplicate after input handoff

Original raw: `/home/ts/wt/g458h/u02/proof/input-frames.jsonl` and Einstein's
`duplicate-frame-receipt.json`, `first-duplicate-frame.json`, predecessor and
strict-review-failure.txt. Product85d45b51/Core970/Text6b; driver214aaacb.
The guarded launch fixes the independently proved renderer bootstrap defect.
The functional five-input journey completed, including actual pending-before-
Started receipts, first fork, busy queue handoff and cancellation. Its strict
original incremental-paint review failed; this is not a whole-journey Ready.

Readonly replay of the original frames through the existing InputRaster found:

| Frame | Original ANSI writes | Physical rows and originating frame |
| --- | --- | --- |
| 982 | No input/answer marker | User30, answer34, both from289590883501351 |
| 983 | Two input markers, two answer markers | User22/30, answer26/34, all from289591039490334 |
| 984 | One input marker, two answer markers | User26, answer30/34, all from289591067215213 |

Thus the duplicate is present in the new update itself. It is not stale pyte
cells, a previous-region classification error or a pending queue caption.
At983 queue and submissions are empty; one mounted original InputStarted
receipt identifies input8ea38cfc351845e390d4b91bacd20f9f, native0220fdb0f97d5ecb61eaeb14393a458e.
Native rendering at completion later shows one answer, which does not erase
the earlier emitted double paint. Runtime DOM/claim custody at983 was not
captured, so semantic double mount versus native layout/render duplication
remains unclassified. Heisenberg owns that publication/paint correction.

No source, observer, oracle, installed package, provider or original disposition
was changed for this analysis. No new application or native process was run.
