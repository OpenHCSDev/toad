# T5 goal-display recovery and caller closure

Source recovered from untouched predecessor `/home/ts/wt/toad-t5-comms-interface-20260928`, HEAD df0a758. Predecessor had no committed T5 changes and no published T5 branch/PR. All 13 tracked diffs, new goal_display.py and four predecessor evidence files were copied into `/home/ts/wt/toad-t5-sol-20260928`; predecessor files remain unchanged. Its old server-poll receipt records a preflight failure, retained as history, not a pass.

GoalBar, GoalDetails and Conversation now have one GoalDisplay state instead of independent optional-goal/unavailable fields. NoGoal, ShowingGoal and GoalUnavailable own visibility, control permission, heading and standby presentation. An unavailable state explicitly retains the last confirmed snapshot. Current UI and ten affected pilot callers use this state; old widget fields/watchers are deleted. Persisted formats and stores are untouched: this batch changes transient presentation only.

Fresh installed-wheel validation used an owned .venv. Toad imports from that environment's site-packages; Comms is installed at the declared 2bfbdb23 revision; Textual/dependencies use the existing immutable runtime-watcher package directory read-only. This does not install into or change the live runtime.

Fresh results:
- recovery-details.txt: mounted full-objective/progress scrolling and draft preservation pass.
- recovery-collapse.txt: mounted collapse, live revision/standby, resize, outage and draft preservation pass.
- recovery-server.txt: actual CommsAgent/Runtime owner reads/mutations, standby, modal updates, outage recovery and bounded reads pass. Explicit fresh private-root/package configuration replaces the predecessor's incomplete test setup. Native package: /home/ts/.local/share/agent-comms/native-entry-store-0d7ebb4f4b5aa1ec/node_modules/@earendil-works/pi-coding-agent. No model calls. The outage segment deliberately injects an owner read error; normal reads and mutations use the actual owner.
- recovery-state-guards.txt: two tests pass, covering display family permissions/new case and absence of retired widget fields.

Remaining T5 scope is NOT complete: sidebar row/RowAction ownership, NavigationTarget.decode retirement, transcript lifecycle/filter state and event merge ownership, DeliveryFailure consumption and class-based sidebar queries. T6 parent supplies ConversationKind; T2 worker supplies ACP extension records/errors; T3 supplies ThreadAction. T5 owns navigation targets and consumes those contracts. Existing 116 workspace chrome/lifetimes remains a distinct owner; this batch creates no alternate workspace mechanism and only changes goal presentation within Conversation. Parent owns D22 activation; this work changes no live root, route or launcher.

Net added code in this batch represents the three-state declaration owner and permanent family/deletion guards. It does not claim the full T5 guards or full-suite readiness. CI is deferred by owner instruction.
