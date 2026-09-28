# PF4 Toad closure — ready for parent installed acceptance

Draft https://github.com/OpenHCSDev/toad/pull/103. Branch `codex/pf4-route-observation-20260928`, tree `/home/ts/wt/toad-pf4-route-observation-20260928`. Base `9523b45` includes feedback PR102.
Stable production `04fb611`: PF4 `ff106b8` plus screen-lifecycle visibility correction. Core pair https://github.com/OpenHCSDev/agent-comms/pull/216 production `cd034e6` (base parent67dcb3c feedback+PF1/PF5). Parent owns current feedback/uncertain-label fixes, integration and activation; no worker live sends/restarts/changes.

Wheel `dist/batrachian_toad-0.6.20-py3-none-any.whl` matches04fb611. Core wheel `/home/ts/wt/comms-pf4-route-observation-20260928/dist/agent_comms-0.1.0-py3-none-any.whl` matchescd034e6. Parent notified each production revision immediately. Later receipt commits do not change wheel bytes.

## Changed production files

- `comms_root.py`: observation delegates to core resolve_comms_route/observe_root, removing full wire construction; current route/marker validated every time. Guarded writes still use existing actual-sink selected_write/guard_default_route_write.
- `app.py`: coordination_wire composes only when validated selection changes; stale concurrently constructed service rejected. No permanent cached root authority.
- `channel_preparation.py`: deleted hidden-only semaphore/previous-result API; retain pending I/O ownership across cancelled waiters.
- `widgets/comms_chat.py`: hidden return precedes route observation; delete prepared-page/warm task/warm completion machinery. Visible read returns through current root/request guards.
- `widgets/message_notifications.py`: identical data/errors don't rebuild text/layout; core status continues polling, no lifecycle parsing/cache.
- `widgets/observed_thread_activity.py` and chat: use existing Screen.is_active for detached/empty-stack transition safety.

Tests: `channel_history_reader_pilot.py` migrates removed background APIs; obsolete `channel_background_warmup_pilot.py` deleted, replaced by `channel_visibility_observation_pilot.py` that proves no hidden route/query and current data on resume.

## Executed acceptance

Use `TMPDIR=$PWD/.artifacts/tests PYTHONPATH=src:/home/ts/wt/comms-pf4-route-observation-20260928/src timeout 60 /home/ts/.local/share/agent-comms/runtime-acp-extensions-20260928/bin/python tests/NAME.py`.

- channel_history_reader_pilot:5cases PASS (scope expansion, attachment basis, identity, bounded revision reuse, cancelled actual I/O retained).
- channel_visibility_observation_pilot:PASS 40hidden ticks no root check/history query, resumed view loads new message.
- default_route_pilot:exit0, mounted private default route flip/stale page rejection/invalid marker and explicit-root selection. Script emits no success output.
- default_route_admission_pilot:exit0, guarded current-root writes/rejection; no provider. Script emits no success output.
- many_tabs_sidebar_observation_pilot:first FAIL in new PR102 timer when app.screen empty; failed log retained. Fixed using existing Screen.is_active, rerun PASS10mountedtabs/40observations/0hidden sidebar refreshes/current rows on return.
- Parent already has prior PR102 notification transition/actual core DM/native activity receipts. Not redundantly rerun here.
- Core17route/entrypoint cases PASS plus20 actual current-route readonly observations,0Comms/registry construction/decodes/buslocks; see core handoff.

No NRA/CI ceremony. No production changes beyond04fb611. Parent handles installed fullUI, real configured-provider send, and original user process. Previous live UNKNOWN isn't retroactively marked successful; this closes the measured route observation churn.
