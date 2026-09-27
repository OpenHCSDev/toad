# Viewport stutter follow-up

Base: merged Toad PR65 at `94507dd0e727acd9ba64494dfd477a33b4800da3`, with
merged Textual PR5 at `4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e` and the preserved
current-main core pin `b1e5bfd5c39ea69c507833e8ed5efc96a7fb038b`.

Status: **draft; tail-frame regression unresolved; not ready to merge**.

## Candidate

`HistoryAnchor` selects an immutable `TailAnchor` or `RecordAnchor` from current
reader intent. Stored policies own compensation; the screen directly calls their
`before_layout`, `restore` and geometry-target contracts. Tail capture no longer
reads a record offset that bottom anchoring never consumes. Record anchoring keeps
its previous offset compensation. Intent transitions rebind before layout so a
reader who scrolls during admission is not pulled back to the tail.

The final draft conservatively keeps the original target-path publication for
both policies. Only the record policy measures the target's offset. The first
measured candidate also omitted tail target paths; that additional change was
withdrawn while investigating progressive-tail rendering.

New `tail_anchor_policy_pilot` fails on the landed baseline when tail capture
requests unnecessary offset geometry. It verifies tail-to-reader and reader-to-tail
transitions during mutations and stable painted record positions. The runner also
includes the existing 2,000-record `history_anchor_geometry` regression.

## Evidence and outstanding failure

- Focused anchor/checkpoint/lifetime suite:6passed18.29s on the initial candidate.
- Initial broader run:77passed,2failed. The route-admission fixture failed while
  deleting its disposable wire with executor work still running; the draft adds
  an executor drain after UI shutdown, preserving its existing route assertions.
- After restoring conservative tail target publication and draining that fixture:
  **78passed,1failed** in269.84s, excluding the separately exercised comms pilot.
- The remaining failure is `committed_history`: during progressive older-page
  admission one painted frame temporarily omits the canonical final reply, despite
  reporting a bottom scroll position. The assertion is unchanged and must remain.
- Three isolated repeats each of candidate and baseline pass this checkpoint;
  the corresponding baseline broader run passes77cases in282.60s. This is not
  enough to label the candidate failure harmless. Do not merge until reproduced
  deterministically and fixed with frame stability retained.

Serial native72-action/52-marker fixture, all filters and drafts retained:

| Capture | Input median / p95 / maximum ms | Loop max ms | GC max ms |
| --- | --- | --- | --- |
| `toad-tail-anchor-control-1` |37.59 /78.85 /86.80|112.85|82.60|
| `toad-tail-anchor-candidate-1` (initial variant) |28.49 /57.06 /64.00|140.65|71.83|

Recorded anchor-triggered full geometry passes (observer records passes of at
least3ms):21in control,0in the initial candidate. Control maximum21.35ms. The
candidate's worst loop gap overlaps71.83ms UI-thread GC. Lower measured input
latency is not proof of an overall maximum-stutter reduction, and these numbers
predate restoration of conservative tail target publication. No final-candidate
latency acceptance is claimed.

Next: diagnose the progressive-tail measurement/publication boundary without
restoring an incidental full-map rebuild or weakening the painted-frame assertion.
Then repeat focused/broad correctness and serial native control/candidate runs.
