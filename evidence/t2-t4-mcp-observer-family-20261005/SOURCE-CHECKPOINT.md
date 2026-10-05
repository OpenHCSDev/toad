# Current MCP observer family: working source checkpoint

Base Toad470 b67020085c72a7aa6a048feaaf4d814fc6a926d7. This draft is NOT Ready and has no execution/import/native qualification.

## Existing producer contract

Core transcript_updates now declares TurnTranscriptUpdate(state=TurnState), published as TurnChangedUpdate. StartedTranscriptUpdate and TurnStartedUpdate/TurnSettledUpdate no longer exist. TurnRunner.replay_turn_state reads the bound original registry; finish_turn/settle_turn releases the exact lease CAS before publication. AcpEventConsumer has no settled method; its compaction handler calls TurnRunner.observe_compaction, which applies CompactionObservation to the existing lease/phase. Progress uses declared CompactionSourceProgress, not old positional counters.

Toad CommsUpdateConsumer admits the actual session before updating ManagedTurnBinding. Agent.current_turn.managed_id and ConversationTurn derive from that binding; the view's MCP note is a rendered projection cleared by accepted idle publication or connection closure. SessionNotificationOwner.receive owns ordered SDK validation. AgentDefinition owns constructor decoding. The physical App screen is now WorkspaceScreen; logical MainScreen remains app.selected_session.

## Concrete partial migration

native_permission_ui now awaits original SessionNotificationOwner.receive, derives managed identity from Agent.current_turn, checks rendered notes instead of deleted _mcp_live_turn, consumes current TurnChangedUpdate, decodes the existing AgentDefinition boundary and selects the actual logical session. External open_observer/session_update/request_permission/disconnected shapes are unchanged.

## Incomplete family (assigned, not abandoned)

mcp_observation_fixture and typed_comms_command_pilot still import the retired producer records and need real acquired registry/lease publication rather than manufactured active fields. Native permission's request decoder and rich-surface replacement must migrate through original JSON-RPC SDK boundary and current presentation lifetime, preserving painted options/preview, explicit offered answer, pending permission across retirement, disconnect cancellation and joined cleanup. This partial observer delta does NOT make these controls runnable or qualify MCP/native behavior.

No production, runtime_fixture, l0a, frozen468, frozen06 or shared recorder edit. No tests, application imports, prefix/holder/native/provider/input/run. Parent priorities source-only recorder wait/deadline closure next; this visible draft preserves the separate three-control repair.
