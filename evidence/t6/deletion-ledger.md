# T6 owner and caller closure

One implementation owner: T6, branch refactor/t6-rendering-20260928, ~/wt/toad-t6-rendering-20260928, PR123. Parent retains integration/live cutover. Base df0a758; current Comms dependency 1853503b432144e9a3becf358bb870b6b71c8119; Textual16ede. Runtime/derived rendering state only; no durable store schema is changed, no cutover/converter is required. Previous worktrees remain untouched.

| Planned owner | Replaced/deleted mechanism | Current caller closure | Evidence |
| --- | --- | --- | --- |
| ConversationKind | HistoryKind, duplicated history/route/page/paint/control selectors | channel_preparation, navigation_preparation, mechanical NavigationTarget migration, app, CommsChatView; T5 owns remaining sidebar/navigation implementation | kind-family, kind-history-current, current-channel-paint, current-dm-paint |
| RenderTask | RENDER_TASK_TYPES, repeated union roster, reusable_result flag | local workers, persistent admission/codec, work_preparation | current-families-final-owner; current-preparation-runtime |
| RenderCommand | RenderCommandKind, paired discriminator/payload match, old envelope helpers, service dispatch registry | renderer server/client; service execute hooks; all current tests | current-families-final-owner; current-persistent-final |
| RenderReply | RenderStatus, optional result/error carrier, client status switch | reply-owned transitions through command progression; rejection distinct from retained failure; decoding stays on I/O thread | current-families-final-owner; current-persistent-final |
| RendererChoice | RendererBackend, create_renderer selector; old adapter name | CLI choice/environment, persisted ChoiceSetting, app startup, runtime adapter and tests | current-selection; current-cli-terminal-short-ipc; current-ui-terminal-startup |
| MessageCategory | enum, label/group rosters, fixed all-category snapshot; hand grouped activity | all live/saved widgets, sidebar filters, transcript preparation/history, route-delivery owner, current pilots | current-categories; current-activity; current-routing-filter; new-case family test |
| TL0 crossing | PreparedPatch.fallback, local obsolete marker wording | patch_diff + tool_call + affected diff pilot | actual installed persistent UI rendering |

Render task reuse remains real: ReusableRenderTask owns its immutable input capture. Markdown reads external project paths and ACP validation opts out; their requests are not shared or retained. Task member discovery derives from DeclaredFamily. Captured Rich/Markdown objects retain the existing pickle dependency contract inside the renderer's private binary IPC; record structure derives from FieldCodec. No alternate text/binary readers are retained.

T5 adoption contract: type[ConversationKind] from toad.conversation_kind; ChannelConversation/DmConversation/IrcConversation; .declared_name for boundary names. Categories are classes from toad.widgets.message_filter, and all_categories() derives current membership. AgentResponse consumes ResponseDelivery; from_route() decodes the genuine optional ACP/transcript routing annotation once. T6 migrates the immediate callers; T5 continues its row/navigation/transcript ownership using these owners. Coordination is recorded on PR121; direct Codex queue was refused for the unloaded spawned-agent handle.

PR110's complete audit is consumed; PR116 workspace/controller/presentation lifetime implementation is excluded. Existing external ZMQRuntime application.compatibility_with(...).require_match() remains its real build-match contract; Toad adds no alias or old-build execution path. Rich's legacy_windows keyword remains the external Rich constructor contract.

Acceptance still requires final performance comparison and final installed rendering/guard receipts after the last codec/category changes. Earlier failures remain recorded; no CI or global-zero-debt claim.
