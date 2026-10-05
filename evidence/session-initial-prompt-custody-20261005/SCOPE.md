# Pending initial prompt custody

Draft source work from actual main `bf9373d73daa58cce6e493f927660c5da1c4432e`.
Heis owns the whole TC1 integration. He directly cleared these production seams;
his viewport body and configured saved-state/original-turn controls are separate.
The #458/#460 renderer operator tuple stays frozen.

## Owner and complete consumer relation

Session requests and SessionAdmissions.launch carry the launch argument into
MainScreen. MainScreen creates the native Conversation through
`_make_conversation`; after successful construction the Conversation owns the
pending value. Constructor failure must leave the original launch value intact.
MainScreen currently keeps that original value after handing it to Conversation.

ConversationSessionBinding owns readiness, shell-prefix interpretation and
submission through the existing UserInputSubmitted/CoreEvent stream. Its exact
transcript identity checks fence asynchronous loading/welcome publications.
SessionViewState captures the same pending input with the original editor,
Undo/history and ReaderPosition before native eviction; acquire restores it
before mounting the new Conversation. Teardown clears the released view, and
close removes the retained state. These existing lifetimes remain in place.

Capture currently leaves the pending value in the old Conversation during
awaited teardown. TranscriptPresentation.close awaits suspend before clearing
its view. Taking the pending value synchronously into the snapshot prevents the
old readiness callback from consuming snapshot-owned input during that interval.
This is a source-supported lifetime counterexample, not an observed replay.

Use the existing ConversationSessionBinding to own one take operation, consumed
by readiness and eviction. MainScreen clears its creation argument only after
successful construction. Keep the existing pre-mount snapshot restoration.
No new class, queue, cache, flag, timer, input policy or native/runtime change.
Patterns: IDEN-5 (one pending fact held by competing actors) and IMPL-12 (the
take-and-clear decision belongs to the current source owner).

`before.json` uses the original refactor-audit Package/FunctionFacts with Python
AST references. Coverage: 288 Toad production, 397 tests and 249 native Textual
modules, zero parse omissions; all seven related owner/consumer files are read.
AST names do not resolve arbitrary runtime monkeypatches and do not prove replay.

## Remaining acceptance

After the coherent source change, compile and measure the exact changed batch.
Prepare one real mounted App control for failed construction, pending eviction,
remount and close while preserving draft/Undo resources. Source and installed
acceptance are distinct. No package/build/App/SDK/provider/input purpose exists
for this draft; accepted project/GUI journeys are not repeated.
