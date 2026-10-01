# Empty native source to first saved file

Source-only actual ToadApp/Window, private canonical Comms storage, original
Agent reader, preparation runtime and native compositor. Frozen dependencies:
Core ba938, Textual 2e49, SDK 0.12.1. No ACP runner, native process, provider,
public root mutation or original u05 input replay.

The old saved history contains the original assigned wire notice and an empty
native source. Its same registered incarnation receives a new private saved
native journal. A settled live answer and the old history must transfer to one
canonical saved resource, keeping the wire notice and readable answer.

Baseline raises NameError in CheckpointPublication's replacement branch: the
loader uses an undefined agent instead of the publication's captured self.agent.
Correcting only that loader exposes two saved histories / two answer resources
when the original queued checkpoint and this operation overlap in preparation.
Both operations captured the same old resource before either mounted its source.

Checkpoint admission now validates that original history against the existing
TranscriptPresentation.histories under the existing history lock. A preparation
whose source resource was replaced declines; it cannot mount another full copy.
The captured original resource is the existing local operation custody, not a
second current-history pointer, content comparison or coverage store (IDEN-7).
All publication-created loaders use the same captured actor; a bounded guard
seals that family contract. No format alternatives or consumer aliases remain.

Candidate: one direct/registered history, one answer resource, original live and
old history detached, saved frontier and loader match, original wire notice
covered, answer in the actual native compositor strips, normal application exit.
This saved-journal fixture has no native input claim rows; native input IDs are
explicitly empty. It does not establish installed ACP/native input readiness.

The original u05 failure-instant widget count and paint remain UNKNOWN. This
reproducer proves both source defects; it does not prove u05 reached either
branch. Preserve u05 and the original native attempt without replay.

Command (from this worktree, bounded to 25 seconds):

```sh
CHECKPOINT_PIVOT_ARTIFACTS="$PWD/.artifacts/checkpoint-pivot-final" \
PYTHONPATH="$PWD/src" timeout 25s \
/home/ts/wt/toad-foreground-readiness-sidebar-followup-20260930/.artifacts/installed-body-readiness-253/bin/python \
tests/checkpoint_source_pivot_pilot.py
```

Files retain baseline NameError, loader-only duplicate failure, corrected receipt
and output. Channel disclosure/publication u04 is a separate pending closure.
