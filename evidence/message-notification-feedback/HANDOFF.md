# Channel notification feedback candidate

Draft PR: https://github.com/OpenHCSDev/toad/pull/102

Stable production commit/wheel: `363b911`. Later commits only update tests/receipts.

Owner: Pascal. Worktree: `/home/ts/wt/toad-message-notification-feedback-20260928`.
Branch: `codex/message-notification-feedback-20260928`, base Toad main101 `d1794c9`.

## Implemented

- Original IRC/Markdown rows own a `MessageNotifications` collapsible, with a concise summary and recipient/state/detail list. Core supplies state, priority and busy; UI groups labels without interpreting lifecycle. Empty/missing result is no recorded outcome; read failures show unavailable.
- One off-thread core batch per visible window, one in flight, every existing observation interval even when bus revision is unchanged. No hidden-screen polling; stale route/target/widget results discarded. Whole-row visibility includes expanded details, independently of existing body-only read acknowledgment.
- DM and native conversations show existing `ThreadView.presentation` through shared `owner_preparation.read_thread_presentation`. Reads stay off-loop. Observed activity cannot begin/settle an ACP turn or change send admission. An ACP Ready event cannot override observed busy channel work. Idle observation restores the normal status; errors say unavailable. Non-Comms empty observations occupy no line.
- Existing TurnStarted activity detail is preserved for thinking as well as working.

## Evidence / candidate

- `pilot-current-4.log`: PASS mounted IRC/Markdown, expand/collapse, Checking/Responding/Checked/Responded with unchanged bus revision, terminal priority over 44 waiting recipients, errors/recovery, batched off-thread bounded reads, hidden/in-flight guards, native Ready override, no invented ACP turn.
- `irc-wrap.log`: PASS existing routed spans, wrapping and keyboard navigation.
- `observed-core-2.log`: PASS actual registry/activity -> core ThreadView -> ACP reader/native conversation and DM, Checking/Responding target text, Ready override, idle recovery, no provider/process launch. First fixture selected its own identity and correctly returned the native tab; fixed test to use a distinct DM peer. Failed receipt retained.
- Failed pilot receipts preserved. Fixed real starvation: notification result was discarded under history refresh lock. Fixed style-remount race by validating current visible row and attached feedback rather than querying removed body children. No current known production blocker.
- NRA attempted once; tool Python cannot parse existing generic-function syntax. `nra.stderr` preserved. Not a readiness gate; no rerun requested.
- Wheel: `dist/batrachian_toad-0.6.20-py3-none-any.whl`, built successfully.

## Parent integration boundary

Requires parent core MessageNotification fields `recipient,state,detail,priority,busy` and batch API. Core commit91d7d61 has them; do not install against old core. Parent installed this wheel and started its real `installed_ui_live.py` acceptance. Parent owns pin update, installed live route/send acceptance, deployment and screenshots; that result is not claimed here. Existing user UI needs reopening to load installed code. No provider calls, live sends, owner restarts or live writes performed by this worker.

`mounted_route.py` is a parent-run optional observer using PRODUCTION ToadApp, never runtime_fixture; normal UI can acknowledge paint. Parent already has `installed_ui_live.py`; prefer that actual-send harness. Do not duplicate sends.

## Commands

```sh
TMPDIR=$PWD/.artifacts/tests PYTHONPATH=src:/home/ts/wt/comms-acp-saved-session-startup-20260928/src timeout 90 /home/ts/.local/share/agent-comms/runtime-acp-extensions-20260928/bin/python tests/message_notifications_pilot.py
TMPDIR=$PWD/.artifacts/tests PYTHONPATH=src:/home/ts/wt/comms-acp-saved-session-startup-20260928/src timeout 60 /home/ts/.local/share/agent-comms/runtime-acp-extensions-20260928/bin/python tests/observed_thread_activity_pilot.py
PYTHONPATH=src:/home/ts/wt/comms-acp-saved-session-startup-20260928/src timeout 60 /home/ts/.local/share/agent-comms/runtime-acp-extensions-20260928/bin/python tests/irc_wrap_pilot.py
uv build --wheel --out-dir dist
```

No side registry, SQL in Toad, status chat records or lifecycle label dispatch remains. New components are UI presentation only. Body read proof and configured agent execution remain with existing owners.
