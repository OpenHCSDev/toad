# PR213 operational resource closure

OperationalSessionSources closes its own shell resource. Removed the screen
argument, foreign Conversation query and conditional choice between two shell
locations; migrated its only consumer in OperationalSessionPresentation.close.
NativeSessionSurface.evict/close already detach the admitted binding before this
finalization. This deletes6/adds4 production lines; it adds no semantic owner,
busy/ready flags or cache. IDEN-3/IMPL-12 owner trace is in the TC1 review.

The old blank_presentation_pilot pinned the removed shared Conversation transfer
path. Updated it to the actual retained session contract with physical tab clicks,
same per-source editor document/history/selection, draft/undo/redo, running shell
detachment/return and final owned process/reader close. Existing project/sidebar
journey remains. Its workspace-global thread-sidebar query selected an inactive
retained source and timed out; preserved that failure, then changed the consumer
to selected_session. No assertion was weakened.

Actual source Toad/Textual application journey exit0 on Coreab/Textual412, no
agent/provider or native owner process. Shell command only sleeps1s and prints
owned-shell-marker. OneUI,40s TERM/5s KILL bound, private persistent TMPDIR.

Command from the persistent PR213 WT:

```
timeout --signal=TERM --kill-after=5s 40s env PYTHONPATH=src:tests \
 TMPDIR=$PWD/.artifacts/owned-shell-close \
 .artifacts/current-pair-package/runtime/bin/python -B -u \
 tests/blank_presentation_pilot.py
```

Receipt: RETAINED_PHYSICAL_ABA_DRAFT_UNDO_SHELL_OWNER_CLOSE_PASS.
Private test directories removed by ordinary teardown; named logs retained in
.artifacts/owned-shell-close. No global install or live owner mutation.
This source proof does not close the separate208 native late-reader-loss failure
or certify installed213. Native activation stays with parent after the repaired
whole integration's actual affected journey passes.
