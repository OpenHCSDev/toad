# Original T4 owner reconciliation

## Scope and result

This is a source reconciliation of the five original obligations in
`docs/refactor/T4-god-classes.md`, dispatched at `67ddc9e`, against merged
Toad #465 `cac7268a733f62f6db57580fd63b64abd52be359`.

The original production responsibilities have existing behavior owners and
their production consumers use those owners. No additional extraction or
product change is justified by this pass. Historical replay and test consumers
still reference removed authorities; they are listed separately below and are
not qualified by this reconciliation.

This receipt does not close the live continuous journey, TC1, frame performance,
or historical MCP controls. It does not repeat the accepted 18-check ordinary
PUBLIC465 journey. Source ownership and installed acceptance are separate.

## Original obligations, storage and consumers

| Original duty | Current owner and stored facts | Related consumers and lifecycle |
|---|---|---|
| Conversation turn permissions, managed identity and ingress ordering | `TurnOwner` owns permissions. `ManagedTurn` derives them and its ID from original Core `TurnState`/`TurnPhase`. `ManagedTurnBinding` owns the current observation, source and publication sequence. `ConversationTurn` observes the Agent presentation binding rather than retaining managed identity or ordering fields in the view. | Prompt submission/busy presentation, compaction command and cancel action query the owner. `CommsUpdateConsumer` admits the session before publishing the binding change. `OwnerSnapshotConsumer` and `AgentController.admits_turn_snapshot` preserve the actual unchanged binding sequence and prompt ordering. `SessionNotificationOwner` validates the captured session request under its original ingress lock; `WireCall` preserves ordered ACP dispatch. Session replacement invalidates original permission/tool/configuration/terminal resources. |
| Outer and inner block navigation | `ContentNavigation` owns the outer cursor. `CursorDirection` owns movement; `AtomicBlockCursor`/`ChildBlockCursor` own selection within a nominal `ConversationBlock`. `admitted_blocks` checks the contract at the mount boundary. | `Conversation.navigation` constructs the existing owner over its actual contents. Cursor actions delegate one movement algorithm; AgentResponse and MountedMessageHistory declare child cursors. Selected-block actions use `BlockContent` capabilities. `MarkdownBlockContent` composes with the original Textual block factory rather than retaining a second block registry or probing `BlockProtocol`. |
| Tab visit/open/close | `TabOrder` alone stores open order, visits and visit cursor and publishes their change signal. | Session admission opens the mode, App records a visit after the actual switch, Sidebar history asks the owner for navigation, and warm admission derives recent modes. `SessionAdmissions.close_many` retires both order membership and original workspace resources. Admission/resource identity and visitation order are different facts; no second order list is maintained by App. |
| Clipboard strategy | `Clipboard.for_platform` selects the original platform transport once. `SystemClipboard` and `TerminalClipboard` own native copy/paste and terminal fallback. The existing Textual clipboard value remains the shared local value. | App copy, Prompt text paste and menu/command/context/path consumers use the owner or the public framework copy boundary. PNG capture remains the distinct external byte/MIME/attachment boundary; its lifetime is not merged into text clipboard strategy. |
| Agent process/task/group lifecycle | `AgentProcess` owns the runner, session/response tasks, attached child, disposition, client custody and one retirement task. Original Core `AttachedChild`/`ChildProcess` owns OS launch identity, process group retirement, pipe release and joined stop. | Agent delegates start/stop and operation tracking. `maintenance_ingress.admitted_spawn` carries original route/wire admission into actual child acquisition; failed/cancelled acquisition joins its worker and retires the observed child. `AgentProcess.stop` and `run` join the same retirement. ACP session/auth/configuration/transcript facts remain with their original owners; they do not repeat OS/group cleanup. |

Relevant source entry points are `conversation_turn.py`,
`acp/{comms_updates,agent_controller,wire_message,client_session,session_updates}.py`,
`agent_presentation.py`, `block_navigation.py`, `block_content.py`,
`conversation_actions.py`, `conversation_markdown.py`, `tab_order.py`,
`session_{admission,navigation,presentation}.py`, `clipboard.py`,
`acp/{agent,agent_process,maintenance_ingress}.py`, `app.py` and the original
Conversation/Prompt/sidebar/mounted-history consumers. Declaration and candidate
consumer sites are retained in `OWNER-CONSUMERS.json`.

## Deleted production authorities

The original dispatch source was read through Git, rather than inferring the
original fields from today's guard strings. Production no longer declares or
uses these original authorities:

- Conversation string `turn`, `_managed_turn_id`, `_mcp_live_turn`,
  `_turn_lifecycle_source` and `_turn_lifecycle_sequence`.
- Navigation `BlockProtocol` switches and the competing movement algorithms.
- App `_open_tab_order`, `_tab_history`, `_tab_history_index` and
  `_supports_pyperclip`.
- Agent root `_process`, `_process_group_id`, `_stopping`, `_agent_task`,
  `_task` and `_active_turn_id` lifecycle/managed-turn authority.

The old Agent `_session_update_lock` responsibility is carried by the original
notification owner; it is not retained as a second Agent ingress lock. A
view's private cursor frontier, Textual clipboard value, local ACP turn member,
session epoch and canonical Core lease are distinct source facts, not replacements
for the removed managed-turn mirrors.

This is the existing implementation's deletion closure, not a new line-count
refactor. IMPL-13 applies to eliminating repeated behavior; AGENT-6 rules out
moving the same shared state into another file to meet a size threshold.

## Remaining unqualified historical consumers

These are concrete source findings at `cac7268a`, not fresh execution failures.
No historical control is repaired by recreating its removed fields or packets.

| Original consumer | Precise stale source | Disposition |
|---|---|---|
| `tools/performance/replay_state.py` | Line 285 writes `app._open_tab_order`. Imports retired `CoordinationUpdate` and old sidebar/category declarations; calls retired `new_session_screen`, `on_coordination_update` and `open_comms_session`. | Heis was asked whether a current loader still needs this offline DTO tool before any deletion or caller migration. Current instructions remain in `tools/performance/README.md`; the successful 13-view historical receipt in `docs/audits/navigation_allocation_20260925.md` remains history. No replay was run. |
| `tests/l0a_native_installed_pilot.py` | Line 397 compares `view.turns.managed_id` with removed `agent._active_turn_id`. | Heis owns the normal continuous-control successor. Frozen #468 `7e61cd22` and active #460 measurement helpers are preserved byte unchanged; this receipt does not patch either. |
| `tests/mcp_observation_fixture.py` | Imports removed `TurnStartedUpdate`/`TurnSettledUpdate`; lines 37/52/54 assert `_active_turn_id` and `_mcp_live_turn`. | Its manufactured packet producer and assertions are unqualified for the current owner contract. Any retained replacement must use the original actual turn/lease producer, not only change the assertion spelling. Current need is not established. |
| `tests/native_permission_ui.py` | Imports `TurnSettledUpdate`; observation/retirement assertions at lines 40/49/53/54/118/119/150 use removed Agent/view fields. | It imports the preceding historical fixture. No static current caller was found; wider dynamic selection is unresolved. No MCP/permission acceptance is inferred. |
| `tests/typed_comms_command_pilot.py` | Lines 54/71 assert removed `_active_turn_id`; the control uses historical manufactured transcript/update producers. | No static current caller was found. Its historical result is not current SDK/lease proof. No rewrite or deletion was made. |

Arendt's direct source answer identifies the current S4 path as
`three_cut_retention_configured_journey.py` ->
`summary_prefix_configured_installed_journey.observe_native_requests` -> sibling
`summary_prefix_native_observer.mjs`, launched through `ParentedProcess` and the
original configured-agent `observe_launch` callback. Neither these three Toad
MCP controls nor a dynamic observer factory is in that current driver path.
The current five S4 source controls do not qualify those Toad controls. This
narrows that dependency uncertainty; it does not prove there is no dynamic
consumer elsewhere.

Before edits, Heis received the exact replay and continuous-control sites and
Arendt received the historical observer question. This branch changes neither
their shared source nor frozen controls. If a current control is required and
unowned, its complete producer/consumer migration is a separate source
checkpoint after the shared seam is acknowledged.

## Source evidence and limits

The existing refactor-audit `Package` parser was used once, without an application
import or a copied scanner. Coverage at the captured revisions is:

| Root | Parsed modules | Parse omissions |
|---|---:|---:|
| Toad `src/toad` | 288 | 0 |
| Toad `tests` | 398 | 0 |
| Toad `tools` | 41 | 0 |
| Core `src/agent_comms` at `3931f16f` | 324 | 0 |

The evidence retains 616 owner declarations and 611 candidate source sites.
Those are candidates read semantically, not proof that all same-named attributes
bind to one receiver at runtime. Factory/MRO/callback resolution is explicitly
limited. Original-field follow-up findings are recorded separately from the
initial symbol selection, which alone found only the replay tab write.

Main465 declares Core `7b68d630caa654d3e9884f45cbd6493718752a0c`.
Original `turn_lease.py`, `turn_phase.py` and `child_process.py` bytes at that pin
are equal to the observed Core `3931f16f` source used for the lifecycle reading.
Their hashes are retained in the evidence. This is source equality, not installed
prefix or runtime provenance. Textual's framework contracts are consumer
boundaries here; this pass makes no fresh Textual runtime claim.

No product/control edits, tests, application imports, prefix access, SDK/native
job, provider input, saved-session access or public operation occurred. Existing
ordinary465 acceptance remains separate and is not rerun or promoted to TC1 or
performance proof.

## Remaining live work

Heis retains the continuous journey, current control integration, TC1 and
paint/performance work. Einstein retains viewport-worker custody. Arendt retains
native measurement/alignment. Sch retains package/publication/native keeper
work, with Parent directing public disposition and Bohr owning holder lifecycles.
This source reconciliation creates no runtime loan or delivery hold. The original
five production T4 responsibilities are closed at source strength; historical
control migration and live workflow/performance results retain their own scope.
