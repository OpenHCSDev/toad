# T6 deletion ledger

Full owner/caller mapping: [OWNER-CALLERS.md](OWNER-CALLERS.md).

Deleted: HistoryKind; RenderCommandKind/RenderStatus/RendererBackend; RENDER_TASK_TYPES and RendererTask/RendererResult roster aliases; optional result/error carrier and status chain; service dispatch registry and old envelope wrappers; MESSAGE_LABELS/MESSAGE_CATEGORIES/IN_OUT_CATEGORIES/static ALL_CATEGORIES; reusable_result marker and admitted flag; optional AgentResponse.route selector; old runtime adapter name; PreparedPatch.fallback. No aliases, dual readers or converters added. Retired structural service tests, unused factory spy and private bus-byte corruption fixture are removed. Permanent guards prevent restoration.

New cases own behavior through inherited ABC contracts and the existing core DeclaredFamily/FieldCodec/MroDispatch mechanisms. Runtime/derived state only; durable history is not rewritten. Genuine ZMQRuntime build-match and Rich constructor contracts remain.

Net source additions are required by declaration-owned task/protocol/category/control behavior and typed reply/delivery contracts; higher-level installed terminal/IPC/new-case tests account for net test additions. Exact source/test line totals are in ACCEPTANCE.md. No positive existing-class growth in the shared ratchet.
