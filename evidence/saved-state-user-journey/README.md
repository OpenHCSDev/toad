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

## Continuous native extension, current installed candidate

The same App now continues through unopened Gamma, an actual held native input,
physical channel-tab click, and the active participant link back to the same
Gamma tab. This removes the separate-path acceptance gap and adds actual
A/B/A document/history/draft/undo/scroll, production fork dialog/first answer,
and channel reply/automatic author observation assertions later in the journey.
No later scenario is claimed executed until this continuous path passes.

Installed Toad d511836d/core77c2ac67/native d3967e8b/Textual1738: startup, channel
click, original-tab return, unopened Gamma attach, and active participant return
PASS. continuous-latest-native.log then fails waiting for the answer to paint.
Retained Gamma ACP Native_fixture_2026-09-29T01_52_23_618909.txt proves actual
NATIVE_RESPONSE_3 received, turn settled and transcript changed. Provider/input
loss is excluded for this attempt; cropped reader/source diagnostics continue.
The earlier continuous-participant-fork-reply.log used old staged420/core942,
with the same timeout. Neither is a whole-journey or live readiness claim.

Shared l0a fixture now retains every test-agent ACP log rather than only primary
Beta. Narrow existing infrastructure extension, no new framework. All imported
product modules are noneditable installed bytes; PYTHONPATH contains tests only.
Parent owns live read-only entrypoint proof and activation. No old142 baseline
hold, no extra agents, paid providers, user input replay, or CI gate.

## Continuous physical native journey PASS

continuous-selected-reader.log exit0, installed d511836d/core77c2ac67/native d396/
Textual1738. Saved startup/channel click/original-tab return -> unopened Gamma
real attachment -> held native input -> active participant click returns same
Gamma -> A/B/A actual tab clicks preserve same Document/EditHistory, draft/undo,
non-tail scroll and exact cropped reader paint -> actual fork dialog creates
normal native child with one first input/answer, parent unchanged, no compaction
or replay -> actual channel working status/reply saved paint and automatic
Beta author native observation with exactly two requests/no ping-pong.

Prior answer-paint RED is conclusively a TEST HELPER defect, not product loss.
participant-return.svg paints NATIVE_RESPONSE_3. Reader diagnostics show selected
Gamma, real answer settled, follows_tail true at scroll25/max25. The old helper
cropped screen.query_one(Conversation), i.e. the retained inactive Beta pane,
with empty region. Replaced that lookup with selected logical source ownership
in existing native_session_retention_pilot.conversation_paint. Actual cropped
paint assertions are preserved; no product edits or alternative renderer.

Deleted 1 stale shared helper ownership lookup line. Pattern IDEN-1: selected
source identity owns viewport selection; IMPL-12: one existing crop helper fixed
for all callers, not a parallel paint mechanism. AGENT-8: one installed continuous
real journey using existing fixture. Remaining explicit strengthening: child
first-open paint and notification detail assertions in this same journey.
Parent latest15603ed adds post-welcome fence and owns actual live gate. This
passing d511 receipt does not attest different product bytes or final latency.

## Final assigned journey closure

continuous-fork-open-notification.log PASS exit0 on the same installed
d511/core77c2/native d396/Textual1738 pair. All previous continuous predicates
remain, plus physical #any child-row click -> actual saved native answer paint
without another model call or parent mutation; actual Responding channel
feedback while the real native reply is held -> Responded -> physical
notification disclosure -> gamma: Responded compositor paint. Original author
Beta automatically observes Gamma reply in its real next native request; no
manual inbox/prompt and no further requests after settling. Six bounded local
provider requests total (two saved Beta, one Gamma direct, one child first input,
one Gamma channel reply, one Beta automatic decision); fixture enforces each
phase count and no replay/ping-pong. No live-user thread/provider used.

Complete changed tests/helpers: saved_state_user_journey_pilot.py,
l0a_native_installed_pilot.py (pre-App prepare callback + all ACP logs),
native_session_retention_pilot.py (selected logical-reader crop). Latest archive
refactor-audit ownership/ratchet applied. closure-ratchet.json measures exact
touched source using canonical skill measures: BooleanChainTerms 0->0 each;
ForeignAbsenceProbe new pilot1->0, shared crop3->3, l0a23->23. No new class
crosses500; ReaderCheckpoint remains a small correct owner. No new product
state/codec/registry/compatibility path. Deleted the stale crop lookup in place.

Retained all three final actual ACP logs with 01_59 timestamps, including child
first-open. Owned generated runtime scratch cleaned by fixture after receipt
copy; tiny PR body removed after publication. Parent owns03ed post-welcome fence
and live gate; this staged d511 receipt does not certify other bytes, every
UI/error surface, final latency, or a whole-product zero-debt claim.
