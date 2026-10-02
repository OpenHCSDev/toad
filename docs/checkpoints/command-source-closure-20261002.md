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
