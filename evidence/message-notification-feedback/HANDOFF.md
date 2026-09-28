# Channel notification feedback candidate

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
- `observed-core.log`: actual registry/activity -> core ThreadView -> ACP reader/native conversation checks passed up to DM navigation. Harness selected existing native tab instead of CommsChatView; correcting this fixture. This is not yet a full DM acceptance receipt.
- Failed pilot receipts preserved. Fixed real starvation: notification result was discarded under history refresh lock. Fixed style-remount race by validating current visible row and attached feedback rather than querying removed body children. No current known production blocker.
- NRA attempted once; tool Python cannot parse existing generic-function syntax. `nra.stderr` preserved. Not a readiness gate; no rerun requested.
- Wheel: `dist/batrachian_toad-0.6.20-py3-none-any.whl`, built successfully.

## Parent integration boundary

Requires parent core MessageNotification fields `recipient,state,detail,priority,busy` and batch API. Core commit91d7d61 has them; do not install against old core. Parent owns pin update, installed live route/send acceptance, deployment and screenshots. No provider calls, live sends, owner restarts or live writes performed by this worker.

`mounted_route.py` is a parent-run optional observer using PRODUCTION ToadApp, never runtime_fixture; normal UI can acknowledge paint. Parent already has `installed_ui_live.py`; prefer that actual-send harness. Do not duplicate sends.
