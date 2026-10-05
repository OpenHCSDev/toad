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

## Current union artifact

Parent subsequently authorized one normal cached Hatchling union build from
frozen `34bd2caa`. It completed in 0.619 seconds. `UNION-FILEWHEEL.json` and
`union-source-inventory.json` bind every one of the 319 Git/checkout/ZIP assets
and all 324 RECORD entries. The new wheel SHA is
`47f8ee49a13762cad3e1224323c3c557bf07df218136e44f087a5f29fce682e2`.
Build metadata remains byte equal; exactly the seven accepted #458 assets
differ from the preserved old `d47bbc52` wheel.

`PROPOSED-UNION-FILEWHEEL-APP-OPERANDS.json` is the effective source-only
proposal. It binds the new artifact to the same unchanged `85fcfcf8` control,
literal future command and paired Core/Textual pins. The original `a70024bb`
proposal and `d47bbc52` wheel remain byte equal. This closes the source artifact
gap without an App, installed-package or native operation.

The mounted NoAgent acceptance remains unrun. Its next eligible holder purpose
is separate; it reserves no slot and yields to Heis's changed cold/frame purpose
if they need the same holder. No accepted renderer or GUI control is repeated.

## Possible alternate holder

Bohr named former style22 as a possible independent holder, not an issued loan.
`PROPOSED-STYLE22-UNION-FILEWHEEL-APP-OPERANDS.json` changes only the future
interpreter/holder slots in the stage and App commands. The original `49c0da1d`
proposal, `47f8ee49` wheel and `85fcfcf8` control remain byte equal; control
arguments, environment, cwd, output and deadline are unchanged.

The alternate proposal leaves actual CURRENT448 floor/archive/preimage/restore
and origin/protected-record bindings explicitly unbound for Bohr's readback.
The older CURRENT444 archive is not treated as current. No prefix was accessed
or reserved. If that actual contract prevents the independent window, #461
follows Heis's cold/frame whole closure.

## First installed proof negative and source correction

The actual issued `f191755c` CURRENT448 purpose staged the retained three wheels
once. The final source proof exited 1 in 1.980446 seconds at its Diff inventory
comparison, before the NoAgent App or native FullTrust job. No App, local UI
submission, ACP, SDK/native process, provider call or model input ran.

The helper assumed that a nearby historical inventory belonged to the digest
in the original typed receipt. That association was not established. Its raw
file digest differs. This proves a defect in the proof control; it does not
prove a changed Diff body, product failure or native failure. The old receipt,
inventory, failed helper and original terminal remain unchanged.

The original four normal file wheels restored CURRENT448 once in 0.210386
seconds. All 1477 captured records and 1883 unchanged other-distribution records
match bytes/modes/links; 69 versions/origins and 626 protected originals plus
five separate original wrapper records match. PREFIXactivation is unchanged.
Two uv environment bootstrap files lie outside those capture lists. Their
actual change times predate this purpose; both were preserved. The append-only
coverage correction reports the missing preimage coverage to Bohr instead of
deleting those files or claiming a captured hash comparison for them.

`installed01-negative/whole-handback.json` binds all 21 original stage, failure,
partial-inventory and restoration receipts. All synchronous children were
waited; their individual birth identities were not retained. The App scratch
was never created. Package/import/operator and matching native READ claims
are returned; independent whole-floor/census closure belongs to Bohr. No retry
or later purpose is inferred.

`SOURCE-PROOF-CORRECTION.json` and `prepared-installed-source-proof.py` reuse the
existing cold460 proof algorithm: authenticate the original cached Diff wheel,
then put its three ZIP/installed members through the existing inventory loop.
The original InstalledSource/VcsPackageDirectUrl owner validates its VCS origin;
a reviewed cache wheel does not change the installed origin to a file URL.
The new proof owns its newly emitted inventory digest. The historical digest
and receipt are preserved. The corrected script parses/compiles and the cached
wheel SHA/member relationship was read; it has not executed against a prefix.

A future proof must bind a fresh literal issued grant, matching native READ
receipt and own output. The existing 85fc NoAgent App control and retained
47f8 union wheel are unchanged. The actual mounted initial-prompt custody
acceptance remains unfinished; no product patch, build or repeated accepted
renderer/GUI journey was introduced to repair this proof control.

Bohr subsequently classified both uv bootstrap files through their original
inodes and change times. `BOOTSTRAP-DISPOSITION.json` binds that independent
receipt: broader extra package files are zero; the missing historical preimage
hash coverage remains explicit. No file deletion or repeated restore occurred.

Bohr independently closed the consumed purpose after verifying the actual
CURRENT448 floor, all 21 owner receipt hashes and fresh privileged clearance
(233 observed UIDs, zero private references/gaps). `INDEPENDENT-CLOSURE.json`
binds the original closure/readback. Matching native READ is returned.
`PROPOSED-CORRECTED-PROOF-NOAGENT-OPERANDS.json` names fresh own proof/App outputs
and the corrected helper plus reviewed Diff cache artifact. A future issued
purpose remains unbound; the unchanged NoAgent App is still unrun.

The inherited descriptive `candidate_sourceproof_binding.own_output` still named
installed01. `PROOF-OUTPUT-CORRECTION.json` preserves that original proposal and
binds the append-only effective output-corrected proposal: this one field now
matches planned proof argv/output installed02. Helper/product/control/artifacts
are unchanged; no proof, prefix access or App ran for this correction.

The corrected installed proof passed in 8.510596 seconds: all 953 packaged
assets, 69 distributions/origins, protected records and matching native
FullTrust. The App remains held. Before its release, Parent identified a
source API error in the control: native DOMNode.id may be assigned once.
`CONSTRUCTOR-CONTROL-CORRECTION.json` preserves the unrun 85fc control and binds
a separate fresh successful-constructor MainScreen. The failed candidate and
pending input assertions remain intact, as do both later local UI events and
all editor/eviction/close assertions. Product, wheels, accepted proof and DTO
are unchanged; only the control parses/compiles here. Its corrected SHA must
be reconciled in the same cf2 lifecycle before the sole App runs.
