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

The working production checkpoint is `759abc2a`: 13 additions/6 deletions across
the three original owner/consumer modules. MainScreen clears its argument only
after successful construction. ConversationSessionBinding.take_initial_prompt
owns take/clear for readiness, eviction capture and final view release. Readiness
still publishes through the same stream and clears only after publication;
shell-prefix interpretation and asynchronous transcript identity checks stay
with that existing owner. Snapshot restoration still occurs before mounting.

The exact three-module local debt delta has no positive counters; no threshold
or exemption changed. The three production modules and the prepared App control
compile. `after.json` binds coverage and the remaining pending member sites.
These are source checks, not an App or replay result.

`tests/session_initial_prompt_custody_pilot.py` prepares one real mounted NoAgent
App control for failed original title acquisition, successful construction,
newest pending eviction/remount, original Document/Undo and Ctrl-Z, a second
remount without replay, and close. `PROPOSED-AFFECTED-APP.json` names the exact
control and its limits. It observes the native event stream without replacing
construction or handlers. Two plain local UI events exercise readiness; original
NoAgent admission refuses them before any backend request. It does not exercise
shell commands, model/native input, arbitrary Textual mount failure or provider
delivery. The control is unrun and its local UI scope requires a fresh purpose.

## Source wheel checkpoint

Parent authorized one source-only build from frozen `2c1da8ed9`. The existing
cached Hatchling 1.28 backend built the normal wheel in 0.713 seconds without
dependency installation, a new environment or installed package changes.
`FILEWHEEL.json` and `source-inventory.json` bind all 319 Git/checkout/ZIP assets,
all 324 RECORD entries and build metadata. The wheel SHA is
`d47bbc52700903cf0929c2b593b4b6f1eeab38980fd21fa8f1e473c376aa7089`.

The declared Core `7b68d630` and Textual `d7337ee0` pins match retained normal
file wheels `a685578e` and `16c9f5e7`. `PROPOSED-FILEWHEEL-APP-OPERANDS.json`
names those artifacts, the unchanged `85fcfcf8` control and a literal future
NoAgent App command. Its candidate holder needs a fresh eligible disposition
and issued purpose; this proposal reserves no slot. It leaves the active joint
#458/#460 wheel, frozen renderer control and package custody unchanged.

No mounted App/SDK/provider/input purpose exists for this draft. The affected
App remains unrun, accepted project/GUI journeys are not repeated, and Heis
retains whole TC1 integration.

## Normal main join

After Parent merged #458, the source normally joined actual main `6d0de99cd`
at `ffd698e5`. The three initial-prompt owner modules and the `85fcfcf8` control
remain byte equal. The seven renderer modules are exactly the accepted main
source. No owner code, control, installed package or active joint artifact was
changed by this reconciliation.

`CURRENT-MAIN-SOURCE-RELATION.json` compares every packaged asset. The retained
`d47bbc52` wheel still matches its original frozen source: 312 assets match this
normal union and seven accepted #458 renderer assets differ. It is not a full
source-equal wheel for the new union. The old wheel and proposal are preserved;
a future #461 purpose must reconcile a normal union artifact before staging.
No additional build, App, package or runtime purpose is inferred here.
