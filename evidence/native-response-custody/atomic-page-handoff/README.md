# Atomic source/resource handoff

Owner: Heisenberg, PR252. Original native/ACP failures g460/u05 and
g458h/u02 remain preserved; no input was replayed. The source counter below
does not identify which branch produced the original frame983.

## Proven source cause

At baseline 6d58fe3a, FollowTailCheckpoint.prepare advanced the mounted
history and awaited a painted batch before CheckpointPublication retired the
original live response. The original App._display observer recorded 21
admitted frames, including two with two visible response resources. Both
duplicate frames had native_mutating=false and preparation_suspended=false.
Final ownership already passed with one response; final counts concealed the
intermediate overlap. See baseline/admitted-frames.json and run.log.

## Ownership change

- Checkpoint preparation receives the publication's original settled cohort.
  Existing CommitClaim coverage decides whether anonymous output transfers.
  Such a transfer prepares an unmounted bounded snapshot, then mounts and
  retires under the existing publication fence. Wire-only advancement keeps
  the original history and anonymous active output.
- Native page and projected page coverage now joins the original transcript
  owner's identity-backed retirement before releasing page admission.
  Standalone saved viewers have no live conversation custody; nested pagers
  cannot certify the canonical direct-child history.
- TranscriptPresentation owns the existing accepted-retirement task for page,
  checkpoint and snapshot consumers. Its shield/join and final prune survive
  caller cancellation. The publication-local definition and queued-page
  coverage are deleted. Handling observation uses its existing worker group.

This uses original native-input IDs, assigned-wire sequences and the captured
source cohort. No body/text deduplication, new lifecycle flags, owner registry,
codec, copied status or compatibility path is introduced. New claim cases
inherit their declaration's coverage behavior without adding a consumer case.
Relevant audit patterns: IDEN-5/6 (original owner/identity), TIME-1/3
(delete the replaced custody definition), IMPL ownership at the declaration.

## Executed boundary

Actual source app, native Textual widgets/compositor, canonical private Comms
storage and source reader; no ACP runner, native owner or provider starts.
Dependencies reused from installed-body-readiness-253; production loaded from
this persistent worktree via PYTHONPATH. This is not installed-pair readiness.

Commands, each bounded to 25 or 30 seconds, with artifact variables naming an
owned .artifacts directory:

    RESPONSE_CUSTODY_ARTIFACTS=... PYTHONPATH="$PWD/src" python tests/response_source_custody_pilot.py
    CHECKPOINT_PIVOT_ARTIFACTS=... PYTHONPATH="$PWD/src" python tests/checkpoint_source_pivot_pilot.py
    CUSTODY_CASE=covered_checkpoint CUSTODY_EVIDENCE=... PYTHONPATH="$PWD/src" python tests/snapshot_cancellation_custody_pilot.py

Candidate: 19 admitted frames, zero duplicate response frames; original wire
Sent/Incoming both once while native output remains held; settled transfer
once; canonical/registered history one; accepted frontier advanced. First
empty-source/native-file pivot once/readable. Cancellation while LiveOutput's
original lock is held joins old-history and covered-stream retirement before
propagating CancelledError. Raw evidence in candidate/, pivot/, cancellation/.

Remaining: normal frozen250 integration, installed native/ACP/LinuxDriver
continuous original input/answer frame review. Source success is not a full
bus/native release claim. PR254 retains performance, warm raster, reader,
focus, TC1/T9 and resource scope. Kepler owns disjoint WorkerStatic PR256.
