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

## Final live-paired installed bytes: single requested rerun

continuous-final-51fdf.log PASS exit0. Exactly one existing complete journey run
on installed runtime-workspace-navigation-20260929: Toad51fdf2b856963b62d3d569ed110d4581ba8a1bf0,
core77c2ac671e80018e75e97d9f8c5643cffe1dd39e, Textual1738abd8e3524b7e86171b70256d7f7e52fdb724,
complete native d3967e8b6ee0cf28. final-51fdf-installed-versions.json records actual
noneditable installed metadata. Test code ddda2345, PYTHONPATH=tests only,
controlled local HTTP responses, private new test root; no existing user thread
mutation or replay. Parent owns separate actual LIVE read-only navigation gate.

Every continuous phase passed: representative saved native startup paint;
physical channel-bar opening and saved channel paint; physical original tab
return; unopened Gamma actual attachment; held native input and active
participant click back to same Gamma with cropped answer paint; clicked A/B/A
Document/EditHistory/draft/undo/non-tail scroll/paint preservation; physical
production fork dialog and first native input/answer with unchanged parent and
zero compaction/replay; physical child first-open/saved answer paint without
new provider input; painted Responding/Responded plus physical notification
disclosure gamma: Responded; actual automatic original-author native reply
observation, saved reply history and no unbounded provider loop. Six bounded
local provider requests. No added matrix, unchanged broad suite or CI wait.

Own branch synced current main51fdf after execution; source/test helpers remain
the exact executed code. Test fixture retired all test-owned children and
removed generated runtime scratch; completed owned scratch closed. No
remaining concrete blocker within assigned157 journey. This receipt does not
claim arbitrary saved data, every UI surface, final latency or global coverage.

## Follow-up: immediate physical fork opening before first answer

Parent157 merged; separate test-only follow-up based current main6a05d5e2.
Existing continuous helper now holds the child first REAL provider response,
physically opens its sidebar row immediately after normal fork registration,
proves real ACP attachment to that child while native execution is active and
first answer absent, then releases and verifies answer paint/unchanged parent/
no duplicate input. All remaining channel/status/reply assertions stay in the
same journey. continuous-immediate-fork-open.log PASS exit0 on installed
51fdf/core77c2/Textual1738/native d396. No manual owner/PID/claim/native seeding.

This is NOT coverage of the newly reported /open command or dead-startup
ENOENT. Current maintained local SlashCommand/CommandCatalog owners contain
no /open declaration. Exact intended command entrypoint is a named contract
dependency on Carver, sole production startup/open owner; requested on153/157.
Do not forward unknown /open syntax to the provider and call that a UI test.
No live user mutation, input replay, new framework or product patch.

Deleted the post-answer-only child row opening, replacing it in place with
pre-answer opening. Latest canonical measure touched pilot: chain terms0->0,
foreign absence probes0->0. All actual phase assertions preserved; strong early
opening PASS is narrower than the real startup failure report. Three follow-up
ACP logs retained. Generated fixture scratch retired normally.
