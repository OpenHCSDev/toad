# T6 renderer ownership and deletion

PR123 is the complete T6 batch in ~/wt/toad-t6-rendering-20260928. Parent owns integration and live activation. T5/PR121 owns rows/navigation UI, T2 owns ACP transport and PR116 owns the separate workspace implementation. PR110's existing audit was consumed. No predecessor/shared/live files were modified, and no model calls were made.

## Shared declarations

- `toad.conversation_kind`: `ConversationKind`, `ChannelConversation`, `DmConversation`, `IrcConversation`. Store `type[ConversationKind]`; decode once at the boundary; derive names with `.declared_name`. HistoryKind is deleted. Page/route/display/control/painted-read behavior belongs to this family. T5 confirmed adoption of 85a63d5 on PR123; subsequent navigation_target implementation remains T5's.
- `toad.widgets.message_filter`: category classes and inherited FromPerson/FromAgent/AgentWork capabilities; `all_categories()` derives current membership. No enum/group/label mirrors remain.
- `toad.widgets.agent_response`: typed `ResponseDelivery`, `UnroutedResponse`, `RoutedResponse`. ACP and transcript boundaries call `from_route` once. Live response streaming, widget presentation and saved transcript consumers carry the typed delivery.
- Renderer choices live in `toad.render_choices`, outside the shared worker import boundary. Renderer tasks, commands, replies and choices use the existing core DeclaredFamily and FieldCodec. Execution, input reuse, command transport, admitted/unadmitted request progression, reply progression and cancellation have their respective owners. RendererTransport owns codec crossing on the existing I/O thread; RendererClient owns handshake/startup. No duplicated dispatch roster or admitted boolean is retained.

## Reuse question answered

RenderPreparation uses task inputs for content-addressed sharing and result retention. ReusableRenderTask owns its immutable captured input, not a marker flag. Markdown depends on project paths; ACP validation opts out. Prepared mutable results are independent per consumer; bounded preparation admission and cancellation remain intact.

## Retired mechanisms and callers

| Owner | Deleted mechanism | Actual callers migrated |
| --- | --- | --- |
| ConversationKind | HistoryKind; history/navigation/render kind switches | readers, app, mechanical NavigationTarget types, CommsChatView |
| RenderTask | RENDER_TASK_TYPES, RendererTask/RendererResult union rosters, reusable_result | worker/service boundary, preparation runtime, persistent admission |
| RenderCommand | RenderCommandKind, paired kind/payload match, old envelope helpers, service singledispatch table | renderer server and client; commands execute existing service operations |
| RenderReply | RenderStatus, optional result/error carrier, status switch, admitted flag | reply-owned progression, cancellation/drain, acknowledgement |
| RendererChoice | RendererBackend, create_renderer, old adapter name | CLI, persisted ChoiceSetting through inherited RendererSettings, app startup |
| MessageCategory | category enum, manual label/group rosters, static all-category set | live/saved transcript widgets, activity, filters, sidebar, streaming response |
| TL0 | PreparedPatch.fallback and obsolete local marker wording | diff and tool-call presentation |

The existing binary pickle contract for Rich/Markdown captures remains inside owner-private IPC. FieldCodec owns the record structure. No text/binary alternate readers, aliases or converters were added. ZMQRuntime's genuine `application.compatibility_with(...).require_match()` and Rich's `legacy_windows` constructor keyword remain external contracts.

## Integration

Fetched current fork main df0a758 and integrated PR117's actual merge e6c5227, which GitHub records on refactor/round2-l0a-callers, not main. ViewportPresentation retains windows/anchors; removed Screen.body_windows/history_anchors are not restored. Dependency pin and lock use deployed core78adae (includes core268); Textual16ede is preserved. Parent completed urgent compaction266/267 and owns live activation.

Shared installed core268 ratchet on core78adae compares T6 against e6c5227: no positive existing-class delta; TypeIdentity unchanged, LongBooleanChain -1, StringSubscript -2. New owners receive null baselines; they are not counted as artificial zero-size old classes. No local ratchet copy was created. Unchanged declaration text was restored to eliminate formatter churn.

CI is deferred by explicit owner instruction. Acceptance uses installed wheels, real process workers/IPC, mounted UI, actual CLI terminal frames and actual Comms log/page/paint boundaries. Native model/ACP revalidation belongs to parent/T2; T6 does not claim that rendering fixtures prove live cold compaction.
