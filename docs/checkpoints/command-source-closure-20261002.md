# Original C0/T3/T4 command source closure

Owner: Mendel. Dispatch source: Toad `b9ebd4c0baf2495e2d74c87c2696458cf4826a87`, Core `1282a4228c7fa2841fab99443478c0f9b3d28a07`.

This is the remaining command membership, submission and publication relation from original T3/T4 and C0. Native lifecycle/compaction489, viewport295, pending channel processing503 and release/reconciliation remain with their existing owners. Schrodinger, Arendt and Heisen granted the named methods. Parent owns the central checklist and activation.

## Concrete current source witnesses

- `command_catalog.py:16-25` filters unavailable target commands before constructing the execution lookup. An ACP-advertised `/pin` therefore survives when that local command is unavailable. Local declarations are intended to own their names.
- `widgets/conversation.py:2202-2230` reconstructs command membership from two registries and tests command subtypes instead of invoking each original command's behavior.
- `acp/agent_controller.py:134,225-227` already owns the original advertised commands. `widgets/conversation.py:478,1577-1579` keeps another converted list. The published event can invalidate the view without copying those source facts.
- `target_commands.py:323-347` stores `TargetSuggestion.help`, copied from the original contextual command and target; presentation can derive it through those original owners.
- Agent input (`conversation_submission.py:104`) and channel input (`widgets/comms_chat.py:373`) consume the same command route. Pointer menus consume `target_commands.py:64`. Editor highlighting and completion consume the catalog projection.

Patterns: IMPL-4/5/7, MEMB-1/2, IDEN-5, BOUND-8, TIME-9. Current archive and installed refactor guidance were read; the archive adds the family-boundary requirement. Syntax counts are leads, not ownership proof.

## Required relation and destination

The existing `CommandCatalog` derives one namespace from original ACP advertisements, `SlashCommand` declarations and `ThreadAction` declarations. Local names retain authority even when their current operation is unavailable. Completion derives availability; execution invokes original command behavior and its canonical target guards. An unknown or genuinely external advertised command remains original input for the ACP submission path.

Reuse `CommandPresentation`, `ContextualCommand`, `TargetSuggestion`, `AgentPresentation` and the existing controller. Delete Conversation's advertised-command copy and subtype/registry dispatch; delete the `TargetLocal` marker and duplicated target-completion helpers. Derive suggestion labels rather than storing them. No new type, catalog, store, status field, codec, format or compatibility reader is planned.

One new local/contextual command or thread action adds its declaration, with zero catalog, submission or pointer-menu branch edits. A new ACP advertisement is decoded from the original controller record and forwarded without reconstructing its original input.

## Acceptance and preservation

Source implementation comes first. Then run affected family/deletion sanity only, and exercise the actual installed native/ACP/UI command and target-menu journey with retained state, keyboard and physical clicks. Check unavailable local/advertised name collision, normal local execution, original external forwarding, hot command publication, target change and return, and pointer/slash consistency. Use existing drivers and controlled provider where appropriate; do not replace UI, state or protocol.

No public input/reset/replay, installed native mutation, owner restart, extra provider model or broad test matrix. Preserve original sessions, goals, UNKNOWN, protected native donors, published release packages and all prior negative/positive proofs. This document tracks a source task; installed acceptance is recorded after it executes.

## Published closure and installed acceptance

Tested source `9e833b462bb931ce544ea5a09ff609c571a0ae90`, with normal main295 integration (`b4a7424c`). Against that current main, seven production files add **99 lines and delete 78**. No new production class; the obsolete `TargetLocal` class is removed. Existing pilot migration adds167/deletes295 lines: the manually attached `true` ACP facade is deleted, replaced by the existing native fixture's original source, saved sessions and real protocol. Model-picker pilot's three callers use the canonical catalog. The existing T3 guard protects deletion of the root dispatcher/copy and retired helpers.

Canonical semantic facts remain `AgentController.commands`, `SlashCommand` declarations, `ThreadAction` declarations and original `TargetContext`/core stores. `CommandCatalog` is an ephemeral derived join, not a persisted catalog or cache. Prompt completion and pointer menu resources project that join. ACP publication invalidates completion; source replacement invalidates it from the newly selected agent. `TargetSuggestion` holds its original command/context resources and derives its label. Submission reacquires the original current context and canonical operation guards. There is no retired-name compatibility route, format change, registry reset or runtime migration.

### None and source-state disposition

Touched-file census reports `none_identity +3`: two catalog availability projections and `ContextualCommand.target_choices` explicitly handle the existing optional `TargetContext` resource. The absence means no contextual target was supplied, never idle/busy/accepted/queued/cancelled state. Its type and original provider remain unchanged; no new nullable field or domain-state flag is added. Catalog execution's missing namespace lookup is external command absence and forwards the original input; its `None` lookup replaces the same previous root lookup. `Conversation.agent` absence remains the existing selected-source resource contract. No private active-turn probe or mirror was added. Original core turn/goal/queue controls and their declarations are unchanged.

### Evidence

Installed acceptance is **PASS,10.717003s**, real `LinuxDriver`, plain `st` on isolated Xvfb `:1`. Actual pointer and X keyboard submission cover retained native-history startup; unavailable local `/pin` colliding with an ACP advertisement (consumed with no native prompt); local `/copy`; a new declaration `/insertion` with zero catalog/dispatcher edits; physical channel open/right-click menu; pointer pin followed by slash unpin; channel copy; A/B/A native return; hot publication of a new external command; and one original `/external ORIGINAL_ARGUMENT_297` reaching native and producing `NATIVE_RESPONSE_3`. Original native/provider envelope contains the exact command line once. Two loopback turns prepared retained native history; one new loopback turn is the forwarding control. No paid call or public input.

Actual PNGs were inspected: glyphs and original saved history remain visible; the pointer menu derives the original channel actions; final native view shows the original input and its response once. The 35s recording has2,099 frames at nominal60fps, plus an8x slowed review and contact sheet with source-video timestamps. The startup contact frames also show a provisional bus-input-verification-unavailable notice during loading, before the retained transcript paints; this gate does not claim that notice never occurs or prove every cursor transition. These are affected-path observations, not a viewport performance claim. Callback action observations have their own acceptance-relative clock; no common video/profile clock is claimed.

- Committed receipt/provenance: `evidence/command-source-closure-20261002/`.
- Installed candidate: `.artifacts/runtime-command297-merged-20261002`; all306 tracked application files/assets match the tested source. Normal69 requirements installed without overrides, `--no-deps` or source overlays; pip check passed. Toad's direct URL honestly names the owned local wheel, not a VCS release commit.
- Cohort: Core`5c74f0ec700e4d83886e2f6fdaea4e1e19ad0d77`, Text`68a0d1cf62fdde8aeef9834836ecf0caf7b169c7`, Diff`8fa7d4d0db993ea3b761c2760ca9b6a56a6251e9`, SDK0.12.1, unchanged fulltrust native5184. No native build/mutation.
- Original recording/native private receipts: `/home/ts/.cache/agent-scratch/toad297-command-source-20261002/gate08` and `/home/ts/.cache/agent-scratch/c297/08`. Earlier failed fixture observations remain named negative receipts; no failed recorder exit was treated as a pass.
- Capture/encoder/Xvfb cleanup errors`[]`, remaining owned PIDs`[]`, remaining private owners`[]`. Private native sessions/proofs retained. No public bus, default launcher, owner or UNKNOWN attempt changed.

Only two affected T3 deletion guards ran; both passed. Same-run census measured only seven touched production files: StringDispatch/TypeSwitch subjects and arms all delta0, class definitions-1, isinstance calls-1. Counts screen admitted ownership; the existing guard and actual native journey establish this named relation. This closes the command membership/submission/publication surface, not the entire original C0/T4 plan or another owner's native/viewport lifecycle scope.

Next: parent reviews and integrates PR297; paired release/default acceptance belongs to the parent. No further unchanged controls or broad tests are required for this source checkpoint.
