# T3 current implementation checkpoint

Branch refactor/t3-commands-20260928, base paired1071d8bf47 (includesT1).

Thread actions implemented: declaration family reuses core Command/DeclaredFamily,
core tool presentation and lifecycle eligibility. Core owner methods return typed
results directly. Menus/messages carry declarations; app executes the command
within existing route admission off the UI loop. Startup completion reconnects
current session views. Fork input collection has one owner; duplicate Main/Comms/
pending screen fork dispatch removed. No persisted state or ACP extension changes.

Current local evidence:
- archive-current.log: mounted menu archives real isolated thread, retains wire,
  goals, identity, native transcript and saved session.
- archive-new-case.log: test-only subclass appears and executes in mounted menu
  without another catalog/caller change; same durable-history assertions pass.
- stop.log: stop stays off UI loop while typing/navigation and view closure work,
  duplicate clicks do not repeat stop, and failures display.
- actions-guard.log: no retired action tool-name literals or string tool catalog
  calls outside declaration owner.
- actions-lint-final.log: affected undefined/unused checks pass.
- archive-first.log: initial interpreter lacked current core Column contract;
  corrected PYTHONPATH to paired current core, no product compatibility added.

Current runner: PYTHONPATH=src:/home/ts/wt/comms-certified-source-bootstrap-20260928/src
TMPDIR=$PWD/.artifacts timeout60 /home/ts/.local/share/agent-comms/runtime-peer-close-20260928/bin/python
 evidence/t1/run_consumer.py tests/{l0a_archive_history,stop_responsiveness}_pilot.py

Remaining T3 work: slash family/current Conversation command consumers after
Nietzsche T2 contract coordination; independent MCP button/state declaration closure
next. T2 retains Agent ACP extension/coordination ownership. Copernicus received
menu contract notification on107; Nietzsche oncore255. Existing actual Agent method
boundaries not changed. This checkpoint is not full T3 completion or deployment.
