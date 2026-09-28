## Complete T6 rendering batch

Implement the complete docs/refactor/T6-rendering.md owner/caller/deletion scope. Consumed PR110 audit; excluded the separate PR116 workspace implementation. Parent owns integration/live activation.

- One shared ConversationKind owns page/route/display/control/paint behavior; HistoryKind is deleted. T5 confirmed early adoption and received the full later contract.
- Tasks are a declared family; immutable input reuse owns real preparation sharing/retention. Deleted RENDER_TASK_TYPES, union rosters and reusable_result flag.
- Commands use existing core DeclaredFamily/FieldCodec and own service execution; replies own progression, result/cancellation/error handling. Deleted kind/payload agreement, status enum/switch, old envelopes, service dispatch table and admitted flag.
- Declared RendererChoice owns startup and persisted ChoiceSetting. UI-only choices live in render_choices; common worker lifecycle remains light. Deleted RendererBackend/create_renderer and old adapter name.
- Categories own presentation through inherited capabilities; catalogs/labels/groups derive from declarations. Live/saved/routed/filter/activity consumers migrate together. ResponseDelivery replaces optional route selectors at ACP/transcript boundaries.
- TL0 PreparedPatch.plain_text and marker cleanup are closed. Genuine external ZMQRuntime build matching and Rich constructor contracts remain. No aliases, converters, alternate readers or old-format path.

## Integration and dependencies

Fetched fork main df0a758 and incorporated PR117's actual merge e6c5227 from refactor/round2-l0a-callers. Preserve ViewportPresentation.windows/.anchors; removed Screen.body_windows/history_anchors remain deleted. Pin/lock current deployed core78adae (includes268 shared per-class ratchet), Textual16ede retained. Parent completed cold compaction266/267; T6 does not duplicate it. T5/121 owns row/navigation implementation; T2/122 owns ACP boundary. Both received direct PR contract handoffs; no further navigation_target implementation edits after the early kind checkpoint.

## Actual local evidence; CI deferred

Installed wheel, no source override/editable installs or paid calls. Real persistent IPC proves result parity, reconnect reuse and cancellation drain. Mounted actual Toad proves Markdown/diff/file preview/Read and viewport restoration; actual terminal CLI proves explicit local and saved persistent choice with clean exit. Actual Comms history/page/paint/DM/filter/category/activity callers pass. Family/new-case tests cover new task/reply/category declarations. Permanent retirement and shared per-class ratchet pass with no positive existing-class delta (TypeIdentity0, LongBooleanChain-1, StringSubscript-2).

Performance: five-case local process pilot1.065s ->1.033s, heartbeat11ms ->11ms; prepared10K-row height0.013ms ->0.010ms; real reconnect+patch134.58ms ->133.87ms. Fixed a diagnosed4.121s worker import regression by removing UI choices from worker startup. Extra serial21-request RPC benchmark: cold median2134.45ms ->2076.86ms; warm32.43ms ->32.89ms (+0.46ms/1.4%); p9555.32ms ->52.39ms. Shared-machine samples do not prove identical latency; raw ranges and the small warm delta are retained, not hidden.

Full receipts, corrections, boundaries and deletion accounting: evidence/t6/ACCEPTANCE.md, OWNER-CALLERS.md, HANDOFF.md. Initial failures are preserved with their fixes; not described as passing suites. No full-suite/native model/live compaction claim. Source1048 added/624 deleted; tests615 added/268 deleted. Net additions implement declaration-owned behavior and higher-level actual installed IPC/terminal/family guards, with no growth in existing classes. Owned disposable exports/artifacts/test roots cleaned; candidate worktree/venv retained for integration.
