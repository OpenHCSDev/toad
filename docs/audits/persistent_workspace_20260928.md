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
