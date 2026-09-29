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
