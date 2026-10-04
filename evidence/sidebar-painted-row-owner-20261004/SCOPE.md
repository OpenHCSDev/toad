# Sidebar paint and tab projection — working source checkpoint

Full performance remains active: rapid/reverse/End/growing history, preparation runway, first paint, CPU/raster, DM/IRC, sidebar drag/scroll, thread opening, retained tabs, focus/draft/Undo, TC1/T9/T4 and configurable 144 Hz. This is not a speed or smoothness result.

## What changed

Current normal-main delta: 13 production files, 122 additions and 171 deletions. Release, sidebar/tab and session-opening changes are source-only, not Ready; final counts derive Git, not earlier four-file checkpoints.

- Existing `SidebarVisibilityObserver.painted_rows` now owns visible-row selection from the original compositor's scene. Left channel projection and right relationship animation both consume it; each original prepared row owns busy eligibility. Removed the separate projection selector and the right panel's walk/update of every busy retained row. Original native attachment, pruning/closing and nearest tree ownership remain; no new roster/cache/map/timer or rate policy.
- `NativeSessionAdmission.tab` selects the original matching `ThreadView` before reading its declaration-owned presentation. Previously each native tab interpreted the entire snapshot roster, although only that one label was used. All `SessionAdmissions.tabs` / `app.open_tabs` consumers benefit. Unread indexing, fallback title, session admission and closure are unchanged. Sch granted exactly this seam; F1 action/deletion hooks are untouched.

The original #422 profile and source paths motivate reading these consumers, but do not establish their CPU share. Current Core611 presentation is a pure projection of captured status/activity/execution, so this change does not claim to remove live process probes.

## Ownership and evidence

Existing native visible custody chooses animation rows; widget mutation stays on the UI thread. Canonical snapshot identity/status and the existing admission determine tab labels. This deletes competing cohort selection/repeated interpretation rather than retaining a second authority (NRA/refactor-audit IMPL-12 / AGENT-2).

`owner-before.json`, `tab-owner-before.json` and `dependency-owners.json` use existing refactor-audit Package/Repository parsing: Toad 288, tests 393, tools 41, Core611 311 and native53 249 modules, zero parse omissions. Nominal declarations/imports/attribute references are source evidence; external dynamic aliases/overrides are not proved. `owner-after.json` records the pushed working source. Evidence lists related declarations/consumers after complete-root parsing; same-spelling ambiguity remains explicit.

## Validation and custody

Source checkpoint only, not Ready. No App/test/recording/package operation has run for these new bytes. Proportionate final checks must cover actual offscreen/reentry busy rows, native/shared tab labels/unread/fallback and growth ratchet after this coherent batch; affected installed validation follows the existing slot's actual handback. No unchanged #422 film replay.

#422 `617e295f1`, raw terminal1/false capture, clipped-peer failure, original film/profile and personal review witnesses remain unchanged. Native52/53's growth correction belongs to Kepler and is not qualified by the old movie. Mendel F4 has exclusive style22 package/execution purpose; this branch reads/edits only its owned checkout.


## F1 native-delete09 shutdown owner classification

Original Sch89ee callback passed hidden-native/selected-history deletion with
A's connection/reader and input bytes unchanged. Whole App shutdown failed later
at NativeSessionSurface._remove -> Conversation.release_native_session: a retained
Conversation had no Window. That callback receipt does not qualify shutdown.

The failed package retains the old global native.close tree-removal pass, followed
by per-view presentation.close disposal, plus the separate MainScreen hydration
worker that calls presentation.prepare again. Our existing422 source removes
those competing release/admission paths; each original presentation owns native
release before native prune. No missing-Window guard or new lifecycle flag is
justified. Source supports a readmission crossing between the two old close
phases; the raw trace has no identities proving that interleaving occurred.

The classification JSON binds actual failed89ee versus owned source392c with full
288-module AST coverage, no parse omissions, declarations/calls and custody writes.
Original422 App warm/actor shutdown acceptance remains a distinct scope. Sch retains
F1 package/process custody; the next changed existing native-delete App case after
a normal422 source join must qualify whole shutdown. No duplicate recording,
provider, new fixture or unchanged89ee rerun.


## Published per-view release and shared sidebar ancestry batch

ConversationSessionBinding constructs the source resources, so its existing close
path now acquires Window and its original cached DocumentViewport before any asynchronous source join. That same acquired
viewport is closed there, with no lazy construction after teardown has started. OperationalSessionPresentation no longer re-queries the
Window after release. Explicit release and Conversation.on_unmount share the base
source-resource cleanup; agent surface retirement and usage publication retain
their distinct unmount lifetime. No missing-node guard, state flag or retry.

The sole production release caller destroys the Conversation immediately afterward.
Deleted its preliminary Contents.remove_children/editor/cursor/ask reset pass:
Native MessagePump already owns descendant teardown during Conversation.remove.
Eviction captures SessionViewState before release, and native binding detachment
retires permission projections before pruning; source actors remain with their
original OperationalSessionSources. This avoids a second DOM destruction/layout
pass rather than hiding Window loss. Actual09 causality remains UNKNOWN; a Window
already absent at resource acquisition still fails, with no false shutdown PASS.

CommsRow and NewSessionButton now take their nearest tree/sidebar from the original
DOM.walk_ancestors weak-parent traversal. Deleted both local parent-walk algorithms;
all row selection/focus/animation/navigation consumers keep their original owner
contract, including detached None and nearest-parent order. No cached parent copy.

Working batch is source-only/untested, not Ready or a stalls-fixed/CPU-gain claim.
F4 has the actual exclusive style22 package/import purpose after Sch's verified
floor restore; no current App/film/package access by Heisenberg. One affected final
App/installed workflow follows coherent source and actual handback. The wider
thread-open/source/admission/preparation/measurement/frame/sidebar workflow stays
active and is not replaced by these local progress checkpoints.

## Original row animation owns busy eligibility

The published four-term panel filter repeated ThreadStatusRow.advance_spinner's original busy decision. Removed that duplicate and migrated both left and right consumers to painted_rows. The observer selects native visible, attached/nonclosing rows belonging to its tree; the original row decides whether advancing its prepared status produces paint. This resolves the specific added long boolean-chain source rather than splitting a guard or relaxing the ratchet. No App/check/package run or performance claim for these bytes.

## Session opening publishes through its real frame owners

Removed the App-wide batch across awaited session retirement/preparation and the
independent atomic/pending navigation flags. WorkspaceSource still owns logical
Loading/Shown selection; NativeSessionSurface still serializes native admission;
HistoryWindow still fences child mutation and compensates its reader; the original
ViewportPresentation readiness and FramePresentation writer receipt still admit
paint. Workspace layout/resize, deferred frame callbacks and tab underlines no
longer consult a second global navigation gate. The unused present_navigation
alternative paint path was deleted after production/test/tool consumer search.

Channel hydration likewise no longer holds all App repaints across child-pump
removal/mount. Its existing route/content generation, source readiness and viewport
publication remain unchanged. These are structural source changes, not proof that
the recorded 422 gaps were caused by this wait or that stalls are fixed. Native
store/workspace switching retains Textual's original short mode-transition mask;
no replacement scheduler, timer, global guard or queue was added.

Existing diagnostics now export the original WorkspaceSource nominal state rather
than removed atomic/pending flags. Removed the obsolete test that asserted those
flags suppress native layout; retained first-paint/held-goal-read checking now
reads the actual native batch depth. Neither checks nor a film have been run for
this checkpoint. F4's sole package/import lease remains protected.

Relationship-row publication also no longer holds the App batch while waiting
for original group member locks, detached ThreadRowsWork preparation or native
row mounts. SidebarGroup.reconcile_groups retains its source witnesses, one
prepared cohort and per-group member custody; each row still publishes its actual
prepared output. Unrelated body/chrome paint can proceed during that work. Source
generation checks and final snapshot/revision publication remain unchanged.

The remaining asynchronous global batches belong to tool subtree and message-style
replacement. Those temporarily destroy their old presentations; removing their
paint fence alone would expose that intermediate tree. They need resource/lifecycle
closure, not blind unindentation. This checkpoint does not claim the whole stall
family closed.

## Integration boundary

The release-only source approved for Sch is the two-file family at e523a93f9 (Conversation and OperationalSessionPresentation). It includes acquisition of the actual cached viewport before the first await. Full #426 also carries unqualified row/tab/ancestry and session-opening changes; its one affected qualification must cover row offscreen/reentry and labels as well as switching/first paint. F1 may integrate only the release family for its changed whole-App native-delete case. Its original09 negative remains immutable; no callback-only shutdown acceptance.

## Deferred work belongs to the selected scene

Removing the global navigation hold exposed its accidental role in callback
custody: a hidden new SessionView can mount under an already-Presented departing
frame. FramePresentation.release now derives the callback's session from original
native ancestry and takes that SessionView's existing current-source relation.
Hidden work stays in the original callback resource until that view's publication;
detached owners are retired. Workspace chrome without a session ancestor keeps
its own current-screen contract. WorkspaceSessions.select already begins the new
frame synchronously before assigning LoadingWorkspaceSource, so an older queued
callback or writer receipt cannot certify the newly selected source.

All original hydration, actor-start, navigation, viewport register/resume/restored
callbacks consume this one release owner with unchanged APIs; no new callback
queue, view registry, flag or capture authority. Native admission and logical
selection remain distinct facts: this does not create or infer an admitted actor,
and each operation retains its original attachment/source checks. Final affected
App qualification must cover hidden cold mounts, current activation, retained
returns and departure/closure during pending source work. This source edge was
not proved as the cause of the old film; no runtime/performance claim.

## Prepared status owns animation eligibility throughout the row family

ThreadStatusRow.busy now derives directly from its existing PreparedThreadRow;
the CSS -busy class remains its paint projection. Left and right timer admission
and the row's advance_spinner all consume the same prepared fact. Deleted all
three reads that reinterpreted CSS classes as status authority. Unavailable and
retired rows already release that original prepared resource; action_status and
native busy inputs keep PreparedThreadRow's original declared semantics. No extra
busy store or new polling/animation rate. Affected installed row checks remain
pending; this changes source ownership, not measured performance.

## Native55 paired resource and original code lease

Kepler froze native55 at bb936deb08cff0b676385007df52759c84356b78
(production a3fe919a4fed230de0380f2587208f909849379f). Its source-qualified normal
filewheel is /home/ts/wt/textual-native-subtree-strips-20261002/.artifacts/text55-filewheel-bb936deb-20261004/textual-8.2.8-py3-none-any.whl,
SHA256 b064011ef5988c395f375ada87e602de61c14f9fa3491315754850d1e97b9611.
The owning source inventory binds all266 assets; native controls14PASS and its
hosted debt ratchet passed. This records the owner's artifact report, not a new
installation/verification by Heisenberg. Genuine BodyMeasurement invalidation and
content refresh calls stay intact; no Toad notify ABI migration is required.

Hosted426 ratchet111379645079 passed at0dfda70b. Later frame-custody and
prepared-status additions require their exact-head hosted result; prior SUCCESS
is not relabeled as the later head's result. No App or physical qualification yet.
F4 remains actual exclusive style22 purpose; no package/source-import borrower is
created by this publication. Following actual handback, the affected App checks
must cover callback-source activation/closure, busy rows offscreen/return and
native/shared tab labels, then the meaningful configured switch/sidebar/motion
journey. Existing source and native controls do not replace that user path.
