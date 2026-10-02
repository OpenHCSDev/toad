# Read-only context tree and detail pane

## Implementation

PR309 now supplies the Context panel at the bottom of the right thread/agent sidebar. The original `SessionPanel` declaration family discovers it; `MainScreen` gives it the selected thread and wire root. It uses native Textual Tree and a read-only, bounded detail pane. No exporter, store, dependency or environment was added.

`toad.core.context_inspection` holds references to original backend observations without importing Textual. Core `ContextManifest`, `ContextSegment`, `NativeContextData`, `SessionRevision` and the existing `context` runtime request own the facts. The UI does not reconstruct Pi branches or compaction, count historical entries as active input, or read referenced files.

## What can be inspected

- Active native system layers, original transcript messages and tool catalog, when the existing prepared owner can supply them.
- Recorded turn manifests, keyed by their original immutable turn identity. These contain provenance, digests, byte counts and token estimates, not historical text.
- Original provenance references, displayed without dereferencing their paths.
- Individual message public text, original tool calls and recorded provider usage. Private reasoning and signatures are excluded through the original `PiMessage` content family.

SDK per-segment counts are explicitly estimates, with their counter named. Provider aggregate totals and archived content are labeled unavailable when the original observation does not supply them. The native observation is before future input and provider hooks; it is not claimed to be a future request capture.

## Lifetime and reader choices

Only expansion and selection intent survive sidebar retirement. Changed native content has a changed original digest in its navigation key. Async detail publication additionally requires the exact currently selected TreeNode.data object: reusing a key across threads or refreshes cannot admit an older result. Both worker groups are cancelled on identity retirement and unmount. Original Textual Signal/MessagePump teardown releases subscriptions.

Coordination invalidations cannot cancel an unfinished context read. The original WorkerManager and completion event own that lifetime; the latest original coordination revision is checked when it finishes. No loader flags, generation store or polling timer were added. Refresh restores the cursor without toggling saved expansion choices.

## Read-only boundary

Browsing supplies no model input, replays no uncertain input, reads no referenced path and makes no provider request. Core547 closes an existing defect where an unprepared `context` request could launch native custody; PR309's affected installed native acceptance must use that paired implementation. Unavailable native detail still leaves the original recorded manifest inspectable.

Long details are prepared off the event loop and bounded before TextArea rendering. Message ranges materialize only when expanded. Untrusted content is literal text, not markup. No live transcript or secret is committed as a fixture.

## Verification status

Source relationships and the whole affected production/dependency AST census were read first. Original saved-thread manifest reads, native content-family projections and actual Textual selection/detail/refresh controls have been checked. Earlier failed actual ToadApp/ACP attempts and exact process cleanup receipts are retained; they are not passes. Actual installed native observation, selected-thread switching and physical UI acceptance remain the final paired check. See `docs/checkpoints/context-explorer309-source.md` for current evidence and the exact dependency.
