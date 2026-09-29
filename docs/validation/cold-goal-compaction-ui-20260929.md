# Automatic goal compaction in the matched installed UI

Draft fixture PR: https://github.com/OpenHCSDev/toad/pull/206.
Production remains owned by the parent. This change extends the existing
`context_compaction_native_installed_pilot.py` with `--goal` and improves bounded
provider diagnostics in the existing native fixture. It adds no production path.

## Verified installation and result

Actual staged interpreter:
`/home/ts/.local/share/agent-comms/runtime-journaled-original-20260929/bin/python`.
The parent's matched installation contains Core `2f9f0f08c9c8204d117a131bb8e17898810f3ebf`,
Toad `8616` (including #201, #204, #205), Textual #412 and native776.
Core #412 subsequently merged as `c13737d18804f746e920d46269214d61f9e363e4`.
This receipt verifies the staged installation; the parent owns default activation.

The completed command exited **0**. `acceptance-complete.txt` records PASS.

- Two real native inputs create retained history through the controlled localhost
  provider. The fixture explicitly stops and starts its private saved owner cold
  after selecting a 10,000-token model window. The saved usage is absent, so the
  native context decision uses stored history. Cold attachment makes no provider call.
- A real editor submission of `/goal` schedules automatic continuation. Toad paints
  `Compacting context…`, the committed summary and the goal answer.
- The 61,054-byte saved file remains an unchanged prefix of the resulting history.
  One journaled compaction commits before exactly one native goal input starts.
  The selected-summary state is linked and there is no pending publication.
- A physical Pause click after the native goal input starts bounds the journey to
  one continuation while preserving its answer. There is no retry or original-user
  input replay, and no paid provider or live-root mutation.
- Seventeen localhost provider calls: two saved-history responses, fourteen
  selected-summary calls and one goal response. The fixture caps calls at forty,
  disables retry, and has a 110-second command deadline. The initial eight-call cap
  rejected legitimate chronological summary chunks; correcting that fixture cap
  preserved the one-compaction/one-goal-input assertions.

## Exact completed command

Run from `/home/ts/wt/toad-agent-tab-state-latency-20260929`:

```sh
TMPDIR=/home/ts/wt/toad-agent-tab-state-latency-20260929/.stream-worker-stages \
L0A_EVIDENCE=/home/ts/wt/toad-agent-tab-state-latency-20260929/evidence/cold-goal-compaction-staged \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-776dc36857e630da/node_modules/@earendil-works/pi-coding-agent \
timeout 110 env TOAD_TEST_ATTEMPT=pr199-cold-goal-staged \
/home/ts/.local/share/agent-comms/runtime-journaled-original-20260929/bin/python \
tests/context_compaction_native_installed_pilot.py --goal \
> evidence/cold-goal-compaction-staged/run.log 2>&1
```

This command has completed; a repeat is unnecessary for this receipt. Each new
run creates distinct fixture input and private saved state. Tag only the interpreter,
not the timeout supervisor, so fixture child cleanup preserves the supervisor.

## Preserved evidence and cleanup

`evidence/cold-goal-compaction-staged/` contains PASS, the exit receipt, painted
compaction/summary/answer frames and the typed journal/input receipt. Compaction
SVG is retained as visual evidence. The fixture never mocks the UI, state or ACP
path. The parent was sent the passing receipt immediately; no further gate remains
with this worker for activation.

The transferred parent `.venv`, global default selection, other owners' worktrees,
source and uncertain inputs are untouched. Removed owned disposable wheel scratch
`/home/ts/.cache/agent-scratch/pr199-stream-worker` (8.7 MB) and Core test stages
`/home/ts/wt/comms-post-cancel-session-custody-20260929/.worker-stages` (1.4 MB).
The successful UI fixture cleaned its disposable stages/private owner processes.
Persistent source, installed worker environment and bounded evidence remain.
Resource check before this serial run: 21.8 GiB home free, 13.4 GiB available RAM,
11.0 GiB swap warning. No helpers or parallel test fleet were started.
