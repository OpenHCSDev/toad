# Saved-state user journey, first substantive checkpoint

Deleted 1 replaced helper signature line. Extend the existing installed native
fixture with a pre-App prepare_state callback; one continuous actual App/Pilot
journey owns the new acceptance. No product changes or new framework.

Owner: Dalton tests/saved_state_user_journey_pilot.py and the narrowly extended
l0a_native_installed_pilot.py. Tesla156 owns workspace/channel production;
Carver153 owns shared navigation/tab callers. Claims coordinated on both PRs.

Actual installed baseline: Toad040607c2 (142), core9251, native4230, Textual1738;
Python imports production from the installed runtime slot, PYTHONPATH=tests only.
Real local HTTP provider, actual Pi/ACP/runtime/native journals, normal Comms
registration/publication and actual App/Pilot pointer clicks. No manual claims,
participant/SQLite seeding, fake Agent/transport/renderer or live-user mutation.

First checkpoint RED: channel-click-readiness.log. Two real native saved turns
before App construction. Actual saved-history startup paint passes. Physical
click on #team returns True but no CommsScreen selection, fails20s deadline.
Source trace: shared CommsRow.screen is WorkspaceScreen, which does not implement
NavigationOwner; SelectTarget falls back to message bubbling. The only handler
is on sibling MainScreen, not an ancestor of shared ChannelsSidebar. Tesla156
received reproducer and exact ownership gap. No fix/readiness/live claim yet.

Earlier seed-stopped-owner receipt is a rejected fixture attempt: explicit Stop
correctly requires explicit Start; prepare_state now retains the normal idle
owner for saved-history UI attachment. Other early runs lost their final trace
because TOAD_TEST_ATTEMPT was also applied to timeout supervisor; fixture cleanup
terminated it. Correct invocation puts env AFTER timeout. Their observations are
retained and are not product regression receipts.

Run (single bounded journey; no extra agents):

    timeout 55 env TOAD_TEST_ATTEMPT=dalton-saved-state-journey-20260929 \
      TMPDIR=/home/ts/.cache/agent-scratch/dalton-saved-state-journey \
      L0A_EVIDENCE=$PWD/evidence/saved-state-user-journey \
      AC_NATIVE_COPIED_PACKAGE=<reviewed-complete-native-package> PYTHONPATH=tests \
      <installed-runtime>/bin/python tests/saved_state_user_journey_pilot.py

Resource assert reports warning /6.6GiB, /home16.1GiB, available RAM14.3GiB,
swap11.5GiB; no fleet added, no broad scans/large suite. Owned persistent scratch
/home/ts/.cache/agent-scratch/dalton-saved-state-journey: disposable provider config,
App DB and generated test state; completed directories cleaned after copying
bounded receipts. Test private wire follows existing /var/tmp fixture requirement,
never stores user source/worktree/history. Source remains persistent ~/wt.

Patterns: AGENT-8 tooling uses existing real fixture; IDEN-1 input acceptance and
painted saved history are different facts; IMPL-12 shared fixture extended instead
of duplicated. No compatibility readers/aliases or second state store. CI deferred.

Remaining in this same coherent journey: corrected channel click/hydration;
participant and unopened-thread opening; A/B/A actual tab clicks with draft, undo,
scroll/custody retained; normal production fork and first input; channel
notification/automatic reply/history/status. Existing installed return-cache
pilot is reused for reader/editor expectations; Tesla owns its file. No blanket
whole-journey or affected-live-entrypoint claim from this first RED checkpoint.

## Repaired installed checkpoint

Same saved-state physical-click journey PASS on staged installed Toad420b9930,
core942f9824, native d3967e8b, Textual1738. Production imported site-packages.
Real two-turn native journal -> actual saved-history UI paint -> actual shared
channel click -> CommsScreen/SAVED_CHANNEL_MESSAGE paint -> clicked original
tab -> savednative history paint, exactly2 providercalls/no replay, no App error.
Receipt repaired-channel-click.log. This is the affected physical native/App
entry path for the channel hotfix, not whole-journey/finallatency completion.
Parent owns affected LIVE path/activation; no live mutation here.
Production selected NavigationOwner now comes from app.selected_session,
resolving the sibling event-bubbling gap. Later feature scenarios continue here.
