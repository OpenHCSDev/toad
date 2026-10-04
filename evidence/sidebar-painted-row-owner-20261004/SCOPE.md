# Sidebar paint and tab projection — working source checkpoint

Full performance remains active: rapid/reverse/End/growing history, preparation runway, first paint, CPU/raster, DM/IRC, sidebar drag/scroll, thread opening, retained tabs, focus/draft/Undo, TC1/T9/T4 and configurable 144 Hz. This is not a speed or smoothness result.

## What changed

Four production files: 21 lines deleted, 14 added relative to frozen #422 `617e295f1`.

- Existing `SidebarVisibilityObserver.painted_busy_rows` now owns busy-row selection from the original compositor's visible scene. Left channel projection and right relationship animation both consume it. Removed the separate projection selector and the right panel's walk/update of every busy retained row. Original native attachment, pruning/closing and nearest tree ownership remain; no new roster/cache/map/timer or rate policy.
- `NativeSessionAdmission.tab` selects the original matching `ThreadView` before reading its declaration-owned presentation. Previously each native tab interpreted the entire snapshot roster, although only that one label was used. All `SessionAdmissions.tabs` / `app.open_tabs` consumers benefit. Unread indexing, fallback title, session admission and closure are unchanged. Sch granted exactly this seam; F1 action/deletion hooks are untouched.

The original #422 profile and source paths motivate reading these consumers, but do not establish their CPU share. Current Core611 presentation is a pure projection of captured status/activity/execution, so this change does not claim to remove live process probes.

## Ownership and evidence

Existing native visible custody chooses animation rows; widget mutation stays on the UI thread. Canonical snapshot identity/status and the existing admission determine tab labels. This deletes competing cohort selection/repeated interpretation rather than retaining a second authority (NRA/refactor-audit IMPL-12 / AGENT-2).

`owner-before.json`, `tab-owner-before.json` and `dependency-owners.json` use existing refactor-audit Package/Repository parsing: Toad 288, tests 393, tools 41, Core611 311 and native53 249 modules, zero parse omissions. Nominal declarations/imports/attribute references are source evidence; external dynamic aliases/overrides are not proved. `owner-after.json` records the pushed working source. Evidence lists related declarations/consumers after complete-root parsing; same-spelling ambiguity remains explicit.

## Validation and custody

Source checkpoint only, not Ready. No App/test/recording/package operation has run for these new bytes. Proportionate final checks must cover actual offscreen/reentry busy rows, native/shared tab labels/unread/fallback and growth ratchet after this coherent batch; affected installed validation follows the existing slot's actual handback. No unchanged #422 film replay.

#422 `617e295f1`, raw terminal1/false capture, clipped-peer failure, original film/profile and personal review witnesses remain unchanged. Native52/53's growth correction belongs to Kepler and is not qualified by the old movie. Sch has exclusive style22 package/execution purpose; this branch reads/edits only its owned checkout.


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
