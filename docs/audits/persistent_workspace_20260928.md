# Persistent workspace continuation of116/110

PR12903685b6 shipping tree is untouched. Own persistent checkout
~/wt/toad-workspace-persistent-sol-20260928 extends that full ancestry and consumes
Carver140f4ec98b8. Merge kept LiveOutput and removed the obsolete widget terminal
inventory. Core301420476a7 and Textualc974 are installed noneditable.

## Actual implementation

- Native WorkspaceScreen owns the original compositor/frame, viewport membership,
  history anchoring and native focus/modal/binding authority. Its fixed header,
  Channels and Footer are mounted once. Session selection never reparents them.
- Existing MainScreen/CommsScreen/PendingThreadScreen/FilePreviewScreen become
  logical SessionView containers. They keep their existing source/presentation
  and navigation behavior; no parallel session renderer or callback dispatcher.
- WorkspaceSessions replaces Textual's per-tab mode/screen stacks for logical
  session membership, lazy mounting, serialized source admission and close.
  The real native modes are workspace/store; selected_session/selected_mode
  expose logical identity explicitly. Native modal stack remains Textual-owned.
- Delete per-screen chrome slots and WorkspaceProjection transfer classes.
  Migrate production tab/history/route/close/preview callers to logical owner;
  selected signal replaces misuse of native mode changes for logical tab changes.
- Source/viewport first-frame callbacks follow the actual native frame. Blank
  editor custody finds its logical surface ancestor, not a former native Screen.
- Relationship identity follows the surface's declared relationship_context;
  delete MainScreen/CommsScreen type dispatch in the observer.

## Evidence and incomplete gates

Installed ordinary blank-session path passed: unchanged native WorkspaceScreen
and SessionsTabs identity, actual original Document/EditHistory/undo, distinct
session drafts, correct selected source. Receipt fourth-installed.log.
Failed earlier installed attempts are retained; they caught duplicate identity,
model-vs-navigation field replacement and a removed Screen focus caller.

Full matched4/16/32/64 actual native ACP/Pi/editor/source/cropped response paint
run is underway. No latency or full116 readiness claim. Original stable30–40ms
median, worst-case spike reduction, native input/modal/frame, real shell/terminal
and revealed sidebar acceptance remain required. Session surfaces currently
rebuild operational Conversation on retirement; source-rebinding/presentation
lease closure remains work, not a completed target. Remaining actual caller
closure and broad suite are not declared passed. No CI hold, paid calls or live
root/install changes. Full NRA/context scan and shared class ratchet follow the
latency run to avoid contaminating its measurements.

## Current integration and owner handoff

Current main e46f8cb5 (129/141/143) is integrated at6f7a3e1; installed pins
are core306 b77db612 and Textualc974. PR142 carries remaining116/110, not a
performance-complete replacement. Original116 fe5493b remains draft until
unique15e4f93 behavior is adapted. No old per-tab Screen/chrome cherry-pick.

The reusable native Conversation now resets declaration values without replaying
history-navigation producers. Typed state restores history positions without
loading editor text. Installed rebind-intent-watcher.log passes original actual
Document/EditHistory/undo, separate drafts and fixed native frame/chrome; watcher
custody promotes the logical lifetime before sharing the widget.

ViewportPresentation now gates every native frame on visible-body readiness,
including rapid PageDown/End outside activation. Readiness checks iterate visible
widgets, not the full source inventory. The installed rapid scroll test uses real
body restoration and cropped compositor text, with no patched restoration. Its
current cold-tail End case fails follows-tail/exact-max acceptance: open blocker.
Recent-source return/reuse acceptance from15e4f93 remains required; old warm-body
8/24 and3-window evidence parameters are not new acceptance targets. Use existing
source/viewport owners and the one shared view budget.

Earlier native4/16/32/64 topology receipt passed all actual source/editor/paint
gates but median258.69ms at64 was not the30–40ms target. New reused-surface full
native matrix, sidebar return, source-close custody, recent-source behavior and
latency/tail closure remain unfinished. CI deferred; no live changes.

### Rapid-scroll caller closure

The cold-tail failure was the remaining `screen.focus_prompt` End binding on the
conversation window. The fixed native WorkspaceScreen no longer owns that logical
action. Window now invokes its actual Conversation owner directly. Installed
rapid-visible-body-local-action.log exits0: repeated real PageDown/End, cropped
tail text, cold dormant tail restored, no submitted visible unready-body frame,
and exact final anchor/max scroll. No mocked restore method. This passes paint
behavior, not repeated-body allocation counts or recent-source switching.

### Shared operational acceptance still red

Fresh actual native4/16/32/64 acceptance exposed operational initial hydration
missing the declared surface slot; compose now always declares it alongside the
loading marker, and the reusable view is no longer data-bound to its first host.
Second native run attaches/navigates successfully, then fails first source swap
with detached Conversation/NoScreen and missing Prompt. Receipts
native-reused-main306.log and native-reused-main306-v2.log are failures, not green
native acceptance. This is own142 integration work; merged livee46 is unchanged.
Inactive editor checks now inspect the actual retained logical owner's typed
Document/EditHistory, and return additionally requires the original editor widget.

## Ordered116 owner handoff5881976193 /144 integration

Merged144 main4147eb1 consumed. Constructor creates GoalSession; source retirement
closes it before new admission. Existing one widget timer resolves the new owner.
Installed goal declaration/activation/stale-binding guards pass2/2 after migrating
actual logical-view test callers. Blank operational-constructor rebind preserves
original editor; rapid cold-tail paint still passes after this integration.

All four ordered obligations remain: (1) fix actual operational swap/same Agent,
queue, permission and editor without replay/restart, publish immediately; (2)
rapid/recent non-tail reuse with bounded memory and real rebuild observations;
(3) matched final-pin loaded+blank4/16/32/64 cropped paint/input/scroll/frame tails
with ordinary GC and stable30–40ms/spike-frequency target; (4) final installed
canonical suite, classify49 predecessor failures as regression versus retired
structure without skipping or extending deadlines. No unrelated audit merge hold.

Current viewport source retirement quiesces its existing worker and releases
layout/paint waits before rebind; this has not passed the actual ACP swap yet.
The native path alternately exposes detached cached Conversation geometry or
message-processing timeout. No assertion/deadline is weakened. CLI thread search
found no Noether handle; direct existing143 thread request5882012192 scopes only
viewport_recent_tabs_pilot adaptation in own tree, no production overlap.

## Concrete source-swap fix — actual native PASS

Standalone fix commitdef847717e56e593e1a1e6b25a6a5a429ad997a7 changes only
SessionObservation.refresh. Exact native diagnostic proved source-close cancels
GoalObservation._run while its UI callback awaits shield(task); cancellation then
escaped into the Conversation message pump with cancelling()==0. Textual exits
the retained pump, leaving detached cached geometry/missing Prompt. The existing
shared observation owner now consumes its own retired-read cancellation while
preserving genuine caller cancellation. No UI leaf catch, replay or restart.

Noneditable actual core3110a1f126d/Textualc974/native5fde native4/16/32/64
acceptance exited0. Eight actual loopback Pi/ACP calls; one rich Conversation;
original Agent/process/queue/native session and real Document/EditHistory/undo
retained; original editor widget reused; response cropped paint all cohorts.
Receipt native-reused-core311-observation-owner.json. At64:169635840 UI RSS,
741 tasks, median126.98ms/max210.86ms,189/189 over100ms. This is improved from
258.69ms but remains adverse against stable30–40ms/spike frequency target.
Measurement includes20ms pilot settle and is not native terminal latency.

Next ordered obligations: recent non-tail reuse/real rebuild count/bounded memory,
final loaded+blank/native input/scroll/frame tails/ordinary GC, then canonical
installed suite classifying49 predecessor failures without skips/deadline growth.
116 stays draft until unique recent behavior/tests are represented.

## Source-message navigation invariant / parent-owned fix

Parent actual main4147 ACP-log UI trace shows ConversationMarkdown link handler
awaiting navigation, while source retirement waits the initiating response pump.
Parent owns narrow production ConversationMarkdown App-worker fix.142 must merge
that fix while preserving logical SessionView path/parser context, without an
alternative workspace navigation mechanism.

New installed tests/persistent_workspace_source_navigation_pilot.py exercises
actual rendered link click -> file read/paint -> physical resize -> return to
original actual editor/Document/EditHistory/undo -> app teardown. It uses a real
owned file and native compositor, no transport mocks; no ACP transport claim.
The pre-parent-fix run hangs (external45sec termination), receipt
source-navigation-before-parent-fix.log; not a passed acceptance. Re-run after
parent fix lands, using the same assertions/deadlines. Actual runner-specific
child-process attestation added. No parent production/worktree edits.

## Main146/147 integration and installed affected-path acceptance

Consumed main14613dd52b and main14719de70c into142, preserving core311 and
Textualc974. Permission dispatch now belongs to request.presentation; the old
Conversation raw dictionary dispatcher and obsolete demo remain deleted. Parent
App-owned preview worker merged cleanly with the logical SessionView parser.
Noneditable installed source-navigation-main147.log exits0: physical link click,
file read and native paint, resize, source return, same editor/Document/History,
undo and teardown. Four observation/goal custody guards pass.

Installed rapid-main147.log exits0 with all original PageDown/End/cold-tail
visible-body assertions. Earlier main146 rapid exit143 was a launcher error:
exporting the cleanup attestation outside Python tagged GNU timeout as an owned
process, so fixture teardown terminated the supervisor. The runner now creates
its own token internally; no assertion or deadline was relaxed.

The new viewport_recent_tabs_pilot uses four actual native loopback calls, three
logical blank tabs, ordinary collection and repeated cropped non-tail source
return. It measures the existing application preparation cache and requires
same Agent/process/editor/document/history without input replay or rich-view
multiplication. This is a new affected-path gate, not a claim that recent source
reuse or final performance is complete.

## Corrected22:16 skill receipt and current ownership deletion

Reread nra-refactoring and actual refactor-audit22:16 at
/home/ts/.local/share/agent-comms/skills/refactor-audit-20260928-2216/refactor-audit,
including changed SKILL, pattern README, implementation IMPL-14 last section and
scripts/audit/chain_terms.py. TIME-9, IMPL-4/5 and AGENT-8 full pattern files were
also read. The official classifier finds absence19 (IDEN-3), not unrelated
predicates, in NativeSessionSurface._can_transfer. The attempted uncommitted
rule-family split was discarded, not shipped.

Deleted BlankSessionPresentation, its late promotion/checker, and duplicate
compose/prepare/retire forwarding. MainScreen now constructs the existing
OperationalSessionPresentation once for blank and native sources alike. The same
OperationalSessionSources owns any actual Agent/shell/directory watcher; empty
sessions simply own no such resource. Removed its unused lock and unreachable
base-close implementation. Blank/shared-channel editor callers use the existing
SessionViewState.editor directly; no compatibility editor_state alias remains.
Official chain-terms receipt shows session_presentation19->0 and main4->0; no
touched file increases chain terms. TIME-9: no store/codec adaptation added;
IMPL-4/5: one complete session custody path replaces promotion and duplicate
dispatch. Actual installed original editor/chrome acceptance passes after deletion.

New real native recent-source acceptance reproduced loss of non-tail intent on
return (cropped selected reader text still paints, follows_tail incorrectly true).
ReaderPosition now owns tail versus offset behavior in the existing history
module; SessionViewState carries that actual source intent. Existing snapshot
publication restores it only after native layout and only if its captured scroll
revision remains current, so a newer user navigation supersedes pending restore.
No retired widget, alternate cache, renderer or source mechanism is retained.

Canonical suite attempt is intermediate, not final acceptance: it was interrupted
once the installed branch changed during independent implementation. Preserve its
failures/summary; do not call it green or final-pin evidence. Its undeclared
pytest-asyncio guard was migrated to the existing asyncio.run convention with
unchanged behavior assertions; observation family/cancellation guards4passed.
Remaining final canonical suite/classification, prepared recent-source reuse,
matched loaded/blank performance and stable30–40ms target are still open.

Canonical intermediate run stopped110failed/43passed after560.78seconds. One
verified category is obsolete native-Screen caller assumptions (for example
acp_sdk_boundary_pilot: WorkspaceScreen.conversation); this is not a blanket
classification of all110 failures. Migrated direct Toad session callers in164
test files to selected_session.conversation/selected_mode; generic Textual App
mode tests remain native. No compatibility forwarding added. Final canonical
suite is not complete, and this interrupted changing-install run is not final
acceptance. Owned test-generated browser/menu receipts restored from own HEAD.

## Main145 paired source checkpoint

Current142 integrates main1459830cb24, including146/147 ancestry; core3228ad034a60d91b0bcb8e90bbeca326e01d2dfb7cc/Textualc9743801. Merge preserved actual tool-owner production contracts and deleted superseded hidden_diff_warmup test. New tool test callers use selected_session without native Screen compatibility aliases.

IMPL-12: ReaderPosition and HistoryAnchor now share WindowRestoration's existing internal scroll-revision custody. There is one restoration template; it suppresses recording internal compensation as a user navigation. Official22:16 chain-term ratchet stays history_anchor4→4/recent pilot0→0.

Installed main145 rapid PageDown/End and cold-tail return passed cropped visible-body paint (`evidence/workspace-persistent/rapid-main145.log`). Recent source native test remains red (`recent-native-main145.log`): saved non-tail19 returns0/max0; returned history admits4 fragments. Same native input/process checks precede the reader assertion. Source admission/range retention is unresolved, owned in142. Initial position gate now waits for actual max_scroll_y>0, using existing native deadline, before selecting the non-tail record. Exact return offset and cropped paint assertions remain unchanged.

This is not full116/110 performance completion or final canonical suite acceptance. Prepared source custody must retain native admitted reader intent with bounded existing PreparationRuntime storage, without a second cache or retained widget tree.

## Native admitted-range checkpoint

IDEN-1: the native CommittedInterval is reused as the immutable identity for a page-admission snapshot. TranscriptPageView captures its own start/stop; no transcript text, widgets, renderer or second cache is retained by ReaderPosition. The offset-reader case prepares that owned admission before SnapshotPublication mounts its history; tail readers continue ordinary newest admission through the same nominal hook.

Installed native acceptance now passes the exact19→19 scroll offset on the first return and original operational-source identity checks. It still fails full cropped conversation paint: a blank row appears above coordination context, shifting the bottom divider outside the crop, although virtual90x55/viewport90x33 and vertical scrollbar agree. Receipt `recent-native-admission.log` remains RED. This is a checkpoint, not recent-source/full116 completion. Older multi-page returns and changed native intervals still require complete prepared-source custody integration; this snapshot does not claim those gates.

Carver owns urgent ViewportPresentation.prepare/native layout reentrancy;142 has no changes to viewport_body.py, session_view.py or WorkspaceScreen layout. No recursion-limit increase or exception masking. Chain-term counts unchanged: transcript_publication21→21/history_anchor4→4/transcript_history47→47/recent pilot0→0.

###148 integration and remaining actual paint facts

Main148b5a40ce is integrated at677563a9. It is terminal crash capture only, not a claim that the reported live RecursionError is fixed. Carver owns its native layout reentrancy sites.

An explicit native after-refresh fence in the recent pilot did not remove the remaining cropped paint mismatch (`recent-native-painted.log`). The same run also exposes an independent canonical-history defect: User divider time changes23:12:33→23:12:34 on source return. Core322 TranscriptEvent has no original native timestamp, while MessageDivider substitutes current time. Core boundary owner requested via142 comment5882920918 to provide canonical event time through existing decode/projections;142 owns the affected Toad caller migration. No second timestamp cache or decoder introduced. Exact full cropped-paint assertion remains unchanged and red.

### Rejected native-extent hypothesis

The fragment trace shows identical admitted12..20 and page89x54 while older/latest AgentResponse heights exchange4/5→5/4. An own experimental capture of committed body extent during retirement did not change this result (`recent-native-extent.log`), so that production patch was removed completely and the installed own wheel restored. No unsupported body-measurement fix is published. The diagnostic caller remains for continued source/leaf investigation. Carver crash sites are still untouched.

## Single-line divider measurement fix

Production commit5eb99066 owns MessageDivider's one-line intrinsic height through the existing INDEPENDENT_HEIGHT method contract (IMPL-4). Native trace found the generic Static measurement wrapping a rule built with the previous self.size.width; divider heights exchanged1/2 across source return. The installed fix yields identical fragment regions/heights/range12..20/page89x53 and retains19→19. No CSS workaround, source replay, Textual/compositor change, recursion limit or exception catch.

Actual installed recent test remains RED solely at full cropped-paint comparison: User and Agent timestamp strings change by one second. The canonical event-time contract request5882920918 remains open; do not erase or normalize those differences in the assertion. Receipt `recent-native-divider-height.log` records the complete actual geometry and text diff. Rapid PageDown/End/cold-tail cropped visible-body acceptance on the same installed wheel passed (`rapid-divider-height.log`, exit0). Chain terms message_divider0→0/recent pilot0→0.

Carver owns authentic live Textual chops[y] IndexError and native layout reentrancy. Neither this fix nor parent150 is claimed to resolve that crash without its own evidence. Full116 prepared-source lifetime/recent reuse/performance30–40ms/final canonical suite remain open.

## Recovered OpenCode intent and149/150 integration

Read `/home/ts/.local/state/agent-comms/opencode-textual-followup.md`, session ses_f313e4945ffeDPKKenjqdrDnPD, plus the predecessor recent-source pilot read-only. It confirms the remaining invariant: recently viewed non-tail source preparation should not repeat, bounded globally; blank median and8/24/three-window historical numbers do not establish full loaded acceptance. Old draft-only hold and old Screen/window pool are superseded. No predecessor files changed or old mechanisms reintroduced.

Main149/150c253 is integrated at091d9c62. Preserve own unconditional visible-body gate and150 native UpdateScroll ownership. Migrate150 pilot to selected logical owner/native frame and zero-argument current prepare contract, retaining reentry, resize, tail, cropped paint and return assertions. Installed `reentry-main150.log` passes. No IndexError resolution claim; Carver owns that distinct current framework failure.

### Existing preparation reuse closes the small-snapshot bypass

Delete the inline fragment-preparation branch and its8192-character/64-event caps. Delete the background switch and migrate its actual TranscriptPageWork caller. Snapshot preparation now uses the existing TranscriptRenderTask declaration and app PreparedRenderer/PreparationRuntime, including small snapshots. No second cache, source controller, codec or protocol added. IMPL-4/5: one execution/reuse path through the declared operation; AGENT-2: actual small caller closure.

Installed four-call Pi/ACP native reader test proves the same exact canonical prepared result stays in the existing bounded cache through first source return:32674 retained bytes of67108864 limit (`recent-native-cache-proof.log`, RECENT_PREPARATION_REUSED). Original Agent/process and19→19/fragment geometry remain. Full cropped paint stays RED only at recreated User/Agent timestamps; do not normalize or drop that assertion. This is prepared-fragment reuse, not a claim that every rich body stays allocated or that30–40ms performance is complete. Final multi-return/multi-page/native inputs/performance/canonical suite remain required.
