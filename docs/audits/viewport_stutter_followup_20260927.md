# Viewport stutter follow-up

Base: merged Toad PR65 at `94507dd0e727acd9ba64494dfd477a33b4800da3`, with
merged Textual PR5 at `4fa6a9c440eaaa7dfaad45a33af146fc4b7e922e` and the preserved
current-main core pin `b1e5bfd5c39ea69c507833e8ed5efc96a7fb038b`.

Status: **draft; tail-frame regression fixed with companion Textual change;
large comms-pilot timeout and remaining latency targets are open**.

## Structural measurement correction

Dependency: [Textual PR6](https://github.com/OpenHCSDev/textual/pull/6), pinned at
`d9f02faf0f1656666e081b7a8734a101a3c4971f`. The merged framework baseline alone
does not contain this correction.

The clipped frame was reproduced with committed geometry evidence: the history
container retained a29-row box while its page already occupied33rows. `NodeList`
publishes structural/display revisions before idle layout messages propagate.
Textual's arrangement cache observed that revision, but its intrinsic box-size
cache did not. The removed full-map lookup had masked that inconsistent state.

The companion Textual change includes the existing child-structure revision in
the box-model cache generation. No extra ancestor traversal, new parallel state
or unconditional layout pass is introduced. Two deterministic tests failed before
the change: nested admission and display-constraint mutation before idle delivery.
They pass after it, retaining width reuse and obsolete-generation retirement.
The full companion framework run passed3,442tests (1skip,4xfail) in193.07s,
followed by six passing scrollbar/Markdown/prune snapshots. A prior run omitted
syntax extras and failed three language tests; the corrected run above includes
them and passes. This dependency-path mistake is separate from the geometry fix.

The progressive-tail diagnostic passed six consecutive runs. The full80-pilot
Toad run then passed79cases, including `committed_history`; only the large comms
scenario exceeded its unchanged100s deadline. An isolated repeat also exceeded
that deadline. A diagnostic showed continuous progress through interaction stages,
and the landed baseline completed in93.75s. This remains an explicit validation
limit, not an all-tests-passed claim or justification for raising the deadline.

## Latest controlled measurements and memory

After the user's X11 restart, validation and native runs were serialized in user
cgroups limited to4GiB RAM with swap disabled. Full Toad validation peaked494.2MiB;
the native control/candidate peaked480.5/475.3MiB, with zero swap use. Only owned
test scopes/processes were retired; no user runtime was restarted.

Serial72-action/52-marker runs, all filters/drafts preserved:

| Capture | Input median / p95 / maximum ms | Loop max ms | GC max ms |
| --- | --- | --- | --- |
| `toad-structural-box-control-1` |33.03 /73.49 /96.75|125.91|89.53|
| `toad-structural-box-candidate-1` |35.65 /56.90 /59.59|112.89|77.00|
| `toad-structural-box-candidate-2` |37.96 /61.93 /69.87|124.73|80.86|

Recorded anchor-triggered full geometry passes (at least3ms):22in control,0in
both corrected candidates. The repeated input tails improved in these runs, but
overall loop maxima still exceed100ms. Keep both repeats; there is no universal
sub50ms or indefinite-aging memory claim.

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

## Earlier evidence and reproduced failure

- Focused anchor/checkpoint/lifetime suite:6passed18.29s on the initial candidate.
- Initial broader run:77passed,2failed. The route-admission fixture failed while
  deleting its disposable wire with executor work still running; the draft adds
  an executor drain after UI shutdown, preserving its existing route assertions.
- After restoring conservative tail target publication and draining that fixture:
  **78passed,1failed** in269.84s, excluding the separately exercised comms pilot.
- The earlier failure was `committed_history`: during progressive older-page
  admission one painted frame temporarily omits the canonical final reply, despite
  reporting a bottom scroll position. The assertion is unchanged and must remain.
- Three isolated repeats each of candidate and baseline pass this checkpoint;
  the corresponding baseline broader run passes77cases in282.60s. This is not
  enough to label the candidate failure harmless. It was retained as a blocker
  until the structural-measurement defect above was reproduced and corrected.

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

Next: finish resolving the large comms validation deadline, then profile remaining
sidebar layout/paint and GC tails. The painted-frame assertion remains unchanged.
