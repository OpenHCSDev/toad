# Readonly04 shutdown custody: bounded diagnosis

No production change, runtime change, provider call, fixture run, owner stop,
or input replay was made for this diagnosis. Production lines deleted: **0**.

## Reviewed boundary

Preserved run:
`/home/ts/.cache/agent-scratch/toad-restored-inbound-chronology-20260929/readonly06-window04`.

Its installed pins are Core `41a83508e579be6c1adf3be28c582da24c865bbe`,
Toad `e59c8b5d1f3512cdd65c5e9c772b3193bf7bbecd`, Textual
`65053c5a2df12249ef1c4193beeff7023c1f75d7`, SDK 0.12.1, and native
`e36a1dde326b70179fa1c854a73fcad61948c90f5a93465a55ddd07d72936f07`.
Actual installed source was read from
`/home/ts/wt/toad-canonical-wire-transcript-20260929/.artifacts/installed-native06`.
Its `acp/agent_process.py`, `acp/maintenance_ingress.py`, `render_backend.py`
and `render_processes.py` are byte-identical to the current Sch215 source
at the time of inspection.

The receipt proves retained original history, 31 observations and three
physical beta/alpha/beta tab clicks completed. The two original native input
IDs are unchanged. This is a completed observation journey followed by a
failed shutdown, not a whole-journey PASS.

## Verified failure ordering

1. Sch's launcher used a 120-second foreground INT timeout. The failure stack
   is in the receiver App's context exit: Textual `_shutdown` → workspace
   presentation close → `AgentProcess.stop` → `gather(runner)` →
   `communicate` → `admitted_spawn`.
2. `AgentProcess.stop` cancels its runner and gathers it with
   `return_exceptions=True`. A runner's ordinary cancellation alone would be
   returned by that gather. External cancellation of the caller can instead
   interrupt the gather.
3. The recorded `admitted_spawn` line 204 raises cancellation **after**
   `await settle(worker)` completed. It does not locate a still-pending OS
   spawn or prove where that worker was waiting before the interrupt.
4. `run.txt` then records `asyncio.Runner` raising `KeyboardInterrupt`.
5. Only afterward does multiprocessing report a dead resource tracker,
   a broken tracker pipe, and attempts to relaunch it while unregistering
   semaphores in finalizers. `bad value(s) in fds_to_keep` originates in
   `resource_tracker._launch` → `spawnv_passfds`.

Buffered phase output in `run.txt` is not a chronological clock. The saved
receipt and first exception ordering are the relevant evidence.

## Process and descriptor ownership

The archived registrations identify alpha as PID 2687299/start ticks
22863665 and beta as PID 2687393/start ticks 22863731. Sch independently
confirmed both fixture processes absent after the run.

The retained kernel samples identify PID 2687245 holding the wire admission
flock. The last sustained observed interval is 100.631–117.447 seconds;
the wire lock is absent at 117.679 seconds. Earlier holds are intermittent.
These samples show same-PID and fixture-owner waiters, but do not identify
which thread or asynchronous task held each open descriptor. The initial
runner identity was not captured in this run. Do not promote this PID-only
observation into an identity-bound lifecycle claim.

No resource-tracker PID, renderer-child PID map, open-FD table, or pre-timeout
task/thread stack is present in the supplied receipt, failure, profile or
kernel-lock artifacts. Therefore the actual invalid descriptor and the
first blocked await cannot be reconstructed from these artifacts.

The source establishes the descriptor roles, not their runtime values:
CPython 3.14 tracker launch passes `sys.stderr.fileno()` plus its newly
opened tracker-pipe read descriptor. Textual's `_PrintCapture.fileno()`
returns -1. Toad prepares the shared multiprocessing tracker before entering
terminal capture, which protects its initial launch but does not establish
the descriptor used during this later relaunch.

## Fixture-specific cleanup concern

The retained pilot runs three production Apps in nested `run_test` contexts.
The test sets `TOAD_TEST_ATTEMPT` before App construction; App construction
starts the shared resource tracker. Its final cleanup calls
`stop_test_children`, which terminates every non-ancestor process whose
environment has that attempt tag. This is broader than the canonical
renderer client's resource lifetime and can target the shared tracker.

This source relation is a concrete custody concern (IMPL-13/AGENT-8), but the
retained evidence does **not** show that helper killing the actual tracker.
Neither nested Apps nor the FD error alone proves the first runtime defect.
The profile contains aggregate calls, not task timelines or stack snapshots;
its cumulative async values are not elapsed shutdown measurements.

## Ownership and disposition

Sch215 owns the fixture/UI observation source; Arendt owns any confirmed S14
stop/join consumer fix; canonical Core `AttachedChild`/`ChildProcess` owns
spawn and identity-bound retirement. Kepler owns this read-only diagnosis.
The existing production custody mechanisms remain unchanged. No parallel
process registry, cancellation algorithm or terminal patch was introduced.

Classification remains: **external timeout interrupted shutdown; downstream
tracker relaunch failed; the first pre-timeout wait and actual FD provenance
are unproven**. Runtime-versus-fixture root cause is not closed. Sch was asked
only for an already-retained task/FD dump; no new probe or replay was requested.
The current hot04 run and original journals were untouched.

Sch subsequently confirmed there is no additional window04 task/FD dump.
The optional five-second pause diagnostic did not fire because that pause
did not block. An older original06 GIL stack belongs to another run and
cannot supply the missing window04 task/descriptor provenance. This closes
the available read-only artifact search; retrospective runtime-versus-fixture
classification remains unresolved. Sch owns a teardown observation at the
next already-required acceptance stage, rather than an additional replay.
