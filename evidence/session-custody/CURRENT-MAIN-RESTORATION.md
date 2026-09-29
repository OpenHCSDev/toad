# PR183 current-main preservation

Review identified that pre-review183 df06f1da lacked newer180 ancestry. Ordinary merge36d3ba35 includes currentmain262e3a9b in full, rather than reconstructing the acceptance block or production method.

`tests/saved_state_user_journey_pilot.py` has zero diff versus262e. Its original independent_source_publication invocation and held GoalWaits lock assertions remain literal and unchanged, including `assert page.events and page.after.session_file` and `ACTUAL_NATIVE_PAGE_DELIVERED_WHILE_STATUS_STORE_HELD`.

`AgentController.restore` has zero diff versus262e. Retained configuration/modes/commands/plan/queue/cursor publish before awaited page I/O; both captured SurfaceBinding and SessionBinding identities guard publication after the await. Controller source diff versus262e is only session-lifecycle migration: SessionBinding.bound, session.closed and session.capabilities.

Affected full installed current-pair journey PASS exit0. Noneditable merged183 Toad; core19e5a0ad, Textual609b74bf, native9213ee71479d1b20. Normal App/Pilot + actual native worker/ACP + controlled localhost provider responses, no paid calls/live mutation/history reset/input replay. Original held-status assertion printed; saved-history startup paint, channelbar/participant click, canonical raw reads [0,0,0], rendered bodies/editor/undo custody, immediate physical fork/open before native first answer, notification working/responded paint, and automatic channel author observation/no replay all passed. No unrelated suite rerun.

Command:

```sh
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-9213ee71479d1b20/node_modules/@earendil-works/pi-coding-agent L0A_EVIDENCE="$PWD/evidence/session-custody/current-pair-journey" TMPDIR="$PWD/.artifacts" PYTHONPATH="$PWD/tests" PATH="/home/ts/wt/toad-context-measurement-sol-20260929/.artifacts/installed/bin:$PATH" timeout 180s /home/ts/wt/toad-context-measurement-sol-20260929/.artifacts/installed/bin/python tests/saved_state_user_journey_pilot.py
```

Full stdout and compressed ACP logs retained. Fixture roots/processes retired canonically. Parent owns merge/live affected-entry installation. No CI hold or new final latency claim.
