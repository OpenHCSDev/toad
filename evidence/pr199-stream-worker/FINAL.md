# Completed installed wheel journeys for paired cutover

Core #411 merge pin: `ae68bc93e701cf3dd35b194260b2cb8cc6d1cb33`.
Toad #205 contains the UI receipt consumer and cancellation notes. Parent owns
global activation with Core #412 goal-compaction repair. These commands have
already completed; no repeat is needed to establish the worker results.

Working directory: `/home/ts/wt/toad-agent-tab-state-latency-20260929`.
Interpreter: `.venv-stream-worker/bin/python`, noneditable installed Core/Toad
wheels. For the parent's matched installation, use its installed Python in place
of the worker interpreter. Each journey creates new private saved state and inputs;
none resumes or retries a user's failed request. Tag only the interpreter, not
the timeout supervisor, so fixture child cleanup cannot kill that supervisor.

## Three cancellation stages, controls, distinct new message: exit 0

```sh
TMPDIR=/home/ts/wt/toad-agent-tab-state-latency-20260929/.stream-worker-stages \
L0A_EVIDENCE=/home/ts/wt/toad-agent-tab-state-latency-20260929/evidence/pr199-stream-worker/cancel-final \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-776dc36857e630da/node_modules/@earendil-works/pi-coding-agent \
timeout 100 env TOAD_TEST_ATTEMPT=pr199-cancel-final \
.venv-stream-worker/bin/python tests/post_cancel_session_installed_journey.py \
> evidence/pr199-stream-worker/cancel-final-run.log 2>&1
```

## Pre-native failure, one Not sent card, draft recovery, distinct new message: exit 0

```sh
TMPDIR=/home/ts/wt/toad-agent-tab-state-latency-20260929/.stream-worker-stages \
L0A_EVIDENCE=/home/ts/wt/toad-agent-tab-state-latency-20260929/evidence/pr199-stream-worker/backend-failure-final \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-776dc36857e630da/node_modules/@earendil-works/pi-coding-agent \
timeout 65 env TOAD_TEST_ATTEMPT=pr199-backend-failure-final \
.venv-stream-worker/bin/python tests/backend_failure_feedback_installed_journey.py \
> evidence/pr199-stream-worker/backend-failure-final-run.log 2>&1
```

## Attachment refusal before any prompt/provider call: exit 0

```sh
TMPDIR=/home/ts/wt/toad-agent-tab-state-latency-20260929/.stream-worker-stages \
L0A_EVIDENCE=/home/ts/wt/toad-agent-tab-state-latency-20260929/evidence/pr199-stream-worker/startup-not-sent \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-776dc36857e630da/node_modules/@earendil-works/pi-coding-agent \
timeout 45 env TOAD_TEST_ATTEMPT=pr199-startup-not-sent \
.venv-stream-worker/bin/python tests/startup_attachment_feedback_installed_journey.py \
> evidence/pr199-stream-worker/startup-not-sent-run.log 2>&1
```

Old installed UI on the identical OS-denied fixture: exit 1, two conflicting
failure cards. See `backend-old-ui/acceptance-failure.txt`. The focused native
cleanup regression injects an IO exception only after the real child exits;
it proves retirement recovery without claiming original cancellation timing
was reproduced.
