# C0/T4: native widget action availability and dispatch

Receiving owner: Mendel. Original row: cleanup-2026-09-29.zip C0-enforce-polymorphism.md Conversation/Question::check_action; parent14 C0 ledger keeps it open. Audited Toad main645d63d1c885ef26f056e34a7c61530c90ce331b. Patterns IMPL-5/7, MEMB-1/4, BOUND-1.

## Census and ownership

Conversation.check_action compares five native action names: terminal focus, modes, cancel, expand and collapse. Question compares selection-up/down/select-kind. PermissionsScreen copies select-kind option/parameter classification instead of querying Question. Native Textual650 checks dynamic availability before dispatching action_<name>, including footer state: True enabled, False hidden, None grayed. The namespace and action syntax are external contracts; that does not excuse keeping our cases as switches.

Heisenberg227 grants methods-only scope: Conversation.check_action and action_focus_terminal/expand_block/collapse_block/cancel/mode_switcher. Mount/layout/history/focus integration remains227. Question availability/action methods and PermissionsScreen forwarding are this receiving scope. Sch229 publication/header methods disjoint. Parent owns canonical turn/input/cancel semantic contract; Arendt443 confirmed public turn.owner.can_cancel / ManagedTurn.phase.can_cancel is the sole availability owner; retain original cancellation worker/two-Escape behavior. No private active-turn probes or state copies.

Existing ApplicationAction parse/apply, KeyboundAction and shared DeclaredFamily are the available owners. Extend the native action contract so action declarations own parameters, availability and effects; generate native namespace/bindings from declarations, not a second command inventory. ThreadAction/TargetContext continue to own durable Comms command permissions, not these widget navigation/choice effects.

## Required closure

Delete both named check_action switches, the copied PermissionsScreen availability logic, and replaced dynamic action methods/callers. Keep one authoritative Question option selection and original Ask callback identity. Native Textual actions not belonging to this widget family retain framework handling. New-case experiment must add a declaration without editing dispatch/availability catalogs. Extend existing T4 guard against action-name dispatch, backed by real historical sites.

Verify installed saved-state Toad with actual native widgets and physical click/key input: retained history block cursor expansion/collapse, question selection and disabled actions, permissions forwarding, draft return. The existing localhost provider supplies controlled answers through the real native/ACP path; no paid calls, replay, live mutation, desktop display or canonical lifecycle substitution.

## Receiving closure — PR230

**Ready for scoped integration review.** Installed source `b7f42d7ced00357aac27b71b08c4d1e85fdd24e3` normally integrates main `fda1b5d2dda13a55a6e3ae400af03a6e76e70ec1` (#229); that merge needed no conflict resolution. The widget action production implementation is unchanged from `5685d357`. This closes the original Conversation/Question action-name dispatch row and its PermissionsScreen consumer. It does not close other C0 rows or the global C3 runtime transition.

### Owner and caller deletion

- Existing ApplicationAction's parameter/effect contract becomes NativeAction; ApplicationAction retains its existing declaration family, app dispatch and palette callers. Existing KeyboundAction supplies native bindings. ConversationAction and QuestionAction use the same DeclaredFamily authority as other commands.
- Each action declaration owns its availability, parameters, binding and effect. DeclaredWidgetActions projects declarations into Textual's native BINDINGS/action method namespace. Textual still parses actions, invokes check_action and dispatches the generated native method. Unowned framework actions retain the framework's superclass contract.
- Conversation's five action-name cases and Question's three-case check_action are deleted. The five replaced Conversation native methods, four Question methods, literal binding lists, Question.DEFAULT_KINDS and copied PermissionsScreen kind/parameter checks are deleted. Screen shortcuts and option hints derive the one SelectKindAction declaration. No second command catalog, status mirror or parameter bag remains.
- Cancel queries the public canonical TurnOwner.can_cancel, as confirmed by Arendt. Its existing worker and two-Escape behavior remain the effect owner. Terminal absence/focus remains a Conversation resource query/effect; block availability remains the original cursor BlockContent owner.
- Original Question options, selection and Ask identity remain authoritative. Selected/empty questions disable all selection effects; selecting a kind returns after one original answer. PermissionsScreen retains one actual native Question resource from construction through mount, preventing an early native binding query from trying to locate an unmounted widget. Its duplicate options member is removed.
- The only kind spelling table is the external ACP PermissionOption.kind shortcut boundary (allow_once/allow_always/reject_once/reject_always). Internal legacy allow/reject kind aliases are deleted; original option IDs are not changed. No state/store format changes or cleanup of historical user state are required.

Against integrated main, the seven production files have **225 deleted lines and 276 added lines**. This includes complete deletion of the repeated availability/dispatch procedures, rather than moving a central switch. The replaced 40-line SlowCancelAgent fake and its disconnected double-Escape test are deleted from tests/comms_pilot.py; the continuous actual native cancellation below owns that behavior evidence.

### Bounded checks and new case

Required debt ratchet, integrated main fda1b5d2 to b7f42d7c: **exit 0, zero positive numeric deltas**. Conversation StringDispatch 1→0 / arms 5→0; Question 1→0 / arms 3→0; affected TypeSwitch counts remain zero. The retained full report is in named scratch; [the small final receipt](../../evidence/native-widget-actions/ratchet-final-summary.json) records the actual delta and seven-file scope.

Three affected existing T4 guards were invoked directly and passed: widget action case-catalog deletion, T4 ownership/deletion, nominal block caller closure. This is not a pytest-suite claim. The existing T4 guard extension has a real historical witness: original check_action bodies contain 7/4/3 conditional sites in Conversation/Question/PermissionsScreen; the candidate contains zero. [Historical witness](../../evidence/native-widget-actions/guard-historical-witness.json).

The installed journey declares ReviewAction and a Question subclass using the existing family. Native F8 invokes the declared effect without adding a dispatcher arm, action roster or widget action method. This is the new-case proof for the admitted owner, not a replacement UI.

### Continuous installed native acceptance

[Installed receipt](../../evidence/native-widget-actions/installed-receipt.json) and [raw journey result](../../evidence/native-widget-actions/action-receipt.json). One real detached private owner, real native e36, ACP and noneditable installed Toad wheel; two bounded localhost requests, zero paid requests. No default/runtime activation or existing owner restart.

1. New controlled input receives actual NATIVE_RESPONSE_1. Actual ACP session reconnect loads its saved native history with the same original process identity and no new provider request.
2. Actual alt+up establishes history focus, native Space expands/collapses the original context block. KEEP_ACTION_DRAFT, original Document and undo-history objects survive the question/modal journey.
3. Native down plus an actual Option label click changes selection. Unavailable A is ignored. Two Enter presses produce exactly one callback with the original answer ID, then selection actions are disabled.
4. The existing PermissionController receives controlled actual SDK options/tool content and opens the real modal. Unavailable r is ignored; a physical navigator click followed by priority a resolves the original modal-allow option. This permission request is controlled through the real client API, not provider-issued.
5. A declaration-only F8 case reaches the native widget effect.
6. A second distinct new input enters the real held native turn. Public can_cancel enables Escape; the first key paints the existing confirmation, the second cancels the original native turn. Its provider disconnect is expected and recorded. No prior input is replayed.

### Actual frame review and limits

The four original native07 SVGs were converted with rsvg-convert and inspected. A fixture preference selects the application's built-in textual-dark theme: the prior default ansi-dark HeadlessDriver export had no terminal palette and produced black frames. Those failed visual receipts remain protected; no image was recolored or retouched.

| Original frame | Observed result |
| --- | --- |
| [Expanded block](../../evidence/native-widget-actions/block-expanded.png) | Native saved response remains visible; actual context expanded, Collapse footer and retained draft visible. |
| [Question options](../../evidence/native-widget-actions/question-options.png) | Actual allow/reject options, selection indicator and native shortcut/footer visible. |
| [Permission modal](../../evidence/native-widget-actions/permission-preview.png) | Approval header and original allowed choice visible. Diff pane had not hydrated at capture; this frame does not prove diff-content rendering. |
| [First Escape](../../evidence/native-widget-actions/cancel-first-escape.png) | Actual waiting native turn, new input and confirmation visible before the second Escape. |

**Separate concrete defect:** after actual saved-history reconnect, NATIVE_RESPONSE_1 appears twice with two Agent headers despite only one provider request for that answer. Schrodinger accepted named ownership of canonical publication/chronology followthrough; original root, native journals and ACP logs are protected. No body dedup, seen list or local publication fix is added here. The C0 action journey passed; it is not a claim that retained-history chronology, warm performance or the whole messaging workflow is correct.

The installed gate uses reviewed Core `224bb8e305bdd47276c4a853749b35e6d7c41ae0`, Textual `65053c5a2df12249ef1c4193beeff7023c1f75d7`, ACP SDK 0.12.1 and trusted native e36. All 272 installed Toad Python files match the tested source; Core's VCS direct_url and 287-file match to the accepted #225 cohort are retained. Early Core000 pairing failures occurred before provider requests because main's existing consumer required CommsForkTool.available_for; no compatibility shim or package-pin change was added. Parent owns coherent paired installation. Arendt's original-registry/nested Thread schema C3 cutover remains open.

### Process and scratch custody

Receiving owner Mendel protects `/home/ts/wt/toad-native-widget-action-availability-20260930` and named scratch `/home/ts/.cache/agent-scratch/toad-native-widget-actions-20260930` (~29 MiB). Source, all seven attempt receipts and retained private roots are persistent. Native07 original root is `retained-native07/private-root/wire`; original journals, input dispositions and settings remain in place.

The existing fixture stopped its private owner and children. A read-only final census found zero processes bearing the exact fixture attempt identity; the original registry's beta ProcessIdentity reports not alive. Inaccessible same-user processes all predate the first fixture by their birth timestamps; other users' inaccessible processes are outside this evidence. The census sends no signals. [Cleanup receipt](../../evidence/native-widget-actions/cleanup.json). No X server or owner desktop was used.

Own installed env/wheel are disposable after review; native package, Core/Textual donor stages and immutable release stage are borrowed dependencies and must not be removed. Default is untouched. Parent updates the global C0 ledger from this receiving receipt after review; no other agent's index, source or proof was edited.
