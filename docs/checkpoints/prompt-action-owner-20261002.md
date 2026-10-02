# Prompt action ownership — issue306

Source checkpoint: main f701c34f13bbe619fc0dd6271c772691ff899b9e, paired Core ad7bf20bc5a30ee7728d4b6f22794ae1cbf49a94 and Textual23822923a02b75a1fad10751d97dc009c36b598b. Final installed source8a5def6e qualified below; no public activation.

## Semantic inventory before implementation

The existing refactor-audit `Package` parser and `FunctionFacts` collected the complete declared Toad production, tests and tools roots, Core production and Textual production. `evidence/prompt-action-owner-20261002/ast-before.json` retains 831 lexical sites, 26 class/member records, imports and action-dispatch decisions across 1,265 parsed Python modules; zero parse omissions. PR60's complete deletion-gate source at5e8812ee83d0dc8714392445bad3e32fc47a1755 was read as the precedent; its helpers were not copied.

| Fact / resource | Existing owner | Consumers / competing paths |
|---|---|---|
| Accepted agent connection | AgentSession.ready, exposed by Agent.ready | Prompt and PromptTextArea both store copied agent_ready. Conversation.agent_ready also serves loading/error/welcome presentation: AgentFail writes True despite the accepted session remaining failed. That field is not valid prompt admission authority. |
| Advertised managed queue capability | ACP AgentController.coordination, published original CoordinationChangedUpdate | MainScreen writes Conversation.queue_supported, copied into Prompt and PromptTextArea. Submission family, queue summary and GoalBar separator consume that copied capability. QueueAttachment separately owns current queue scope/availability; advertisement is not queue freshness. |
| Active turn permission | TurnOwner / ManagedTurn.state | Prompt/editor agent_busy properties already derive original TurnOwner. Preserve these original source relations. |
| Action eligibility and execution | NativeAction plus DeclaredWidgetActions | PromptTextArea.check_action separately switches on submit_now/clear_input; SendNow click and message handler invoke action_submit_now directly, bypassing Textual availability. |
| Local unsubmitted editor intent | PromptSubmission scheduling and PromptTextArea._submit_pending/_submit_immediate | These are pending local event resources, not accepted native input state. Preserve typing/paste ordering, coalescing and eventual UserInputSubmitted.immediate. |
| Accepted input identity and request lifetime | InputSubmission family, SubmissionExecution, ClientSessionRequest and QueueAttachment | Ordinary/deferred/immediate/empty SendNow paths must consume the original capability, retain request and scope fences; no lifecycle implementation changes or replay. |
| Local composer / goal editing | Prompt.simple_input and shell_mode, ChannelPrompt | Channel and goal editors can submit without an ACP session. Distinct local editing behavior must not be forced into accepted-agent readiness. |
| Selected model/mode/thinking | AgentConfiguration and AgentController | Already merged302; this scope adds no selected configuration copies. |

## Implemented owner closure

Extend existing action behavior with Prompt declarations rather than another dispatch mechanism. The original accepted Agent/session supplies native prompt readiness; the existing agent presentation exposes the original advertised queue capability. Delete Prompt/editor readiness and queue copies and the upstream queue-capability flag, with all producers, bindings, submission, display and separator consumers. Preserve local editing/scheduling resources and canonical turn/queue admission fences. Coordinate accepted-source and lifecycle semantics with Arendt; no competing lifecycle edits.

The AST inventory is lexical evidence, not dynamic receiver resolution. Textual data_bind/getters, generated partialmethod actions and inherited methods require source reading; no resolved-call claim is made for them. The existing NRA parser also parsed all38 installed SDK0.12.1 modules, retaining11 relevant transport/schema declarations in ast-sdk-boundary.json; no parse omissions. Native provider activity is independent concurrency and is not deleted as a competing UI authority.

## Final validation and receipt

After coherent implementation and after-source declaration/consumer output, use one focused sanity batch and one installed application journey for actual keyboard/click availability, ordinary/immediate/empty queue dispatch, refusal, local composer and retired attachment behavior. No public/uncertain input replay. The completed304 receiving journey and raw negative oracle evidence remain unchanged.


### Shipped scope

Existing NativeAction + KeyboundAction + DeclaredWidgetActions compose through Python MRO: PromptAction specializes the context, and the existing submit/submit_now/clear effects and binding definitions are its three load-bearing members. No parallel dispatcher, registry or readiness family was added. SubmitNowAction.available is the only eligibility decision, shared by native keyboard dispatch, actual SendNow clicks and delivery-control rendering.

Accepted readiness derives from AgentSession.ready through the original Agent. Queue advertisement derives from original AgentController.coordination through AgentPresentation. QueueAttachment owns freshness and request capture independently. Deleted both Prompt/editor readiness and queue var definitions/binders, the MainScreen→Conversation capability flag, separate check_action string dispatch, direct click bypass, duplicated binding/effect declarations and dead GoalBar reactive watches. All original submission-family callers read the derived existing view properties. Queue publication invalidates derived readiness/bindings/rendering without creating semantic state.

Conversation.agent_ready remains a distinct settled loading/welcome/error presentation signal: AgentFail intentionally marks that resource settled. It cannot authorize Prompt or editor submission after this change. No claim is made that this historical presentation lifecycle is fully refactored; the AST receipt explicitly lists its remaining writers and historical fixture consumers. Local pending UI callback and immediate intent remain with PromptSubmission; they are not accepted native state.

Production:8 files,103 added/63 deleted. Existing fixtures:10 added/78 deleted, including removal of the obsolete separator pilot that assigned copied queue support and attempted to assign a derived turn owner. Source after-census lists no queue_supported writes in production/tests/tools. Every generated action hook remains owned by DeclaredWidgetActions; AST does not claim dynamic receiver resolution.

Normal immutable installed69-package candidate: `.artifacts/runtime-prompt-action-owner-20261002`, frozen Toad8a5def6eb5141256e844fb6b659a8be0cf70fa25/Coread7/Text238/SDK0.12.1/Native5184. Complete source, assets, directURL, dependency and native trust receipt: `.artifacts/prompt-action-owner-20261002/source-proof.json`. Public candidate304/package bytes remained unchanged.

Actual installed continuous Toad/ACP/Native5 journey02 PASS/exit0: original accepted session readiness and queue advertisement; idle refusal; ordinary input/first reply; warm A/B/A; native rename preserving SDK/session/scope lineage; busy availability; deferred original input; physical SendNow click; original native start/reply; draft preservation; empty queue/settled input; idle refusal; cleanup0. Four bounded controlled localhost provider requests; no paid/configured-provider or compaction acceptance claim. Actual SVG and wire/native/ACP proofs remain in the owned persistent private fixture. The initial stdin-launched driver failed multiprocessing entrypoint recovery; its one local request and negative proof remain preserved, and its root was not replayed.

Committed READY/source/AST receipts are in `evidence/prompt-action-owner-20261002/`. Parent alone owns merge/publication. Completed304 controls were not repeated. No overall CPU, full lifecycle or arbitrary model-capacity claim.
