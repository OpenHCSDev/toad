# Prompt action ownership — issue306

Source checkpoint: main f701c34f13bbe619fc0dd6271c772691ff899b9e, paired Core ad7bf20bc5a30ee7728d4b6f22794ae1cbf49a94 and Textual23822923a02b75a1fad10751d97dc009c36b598b. No production changes or validation yet.

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

## Planned owner closure

Extend existing action behavior with Prompt declarations rather than another dispatch mechanism. The original accepted Agent/session supplies native prompt readiness; the existing agent presentation exposes the original advertised queue capability. Delete Prompt/editor readiness and queue copies and the upstream queue-capability flag, with all producers, bindings, submission, display and separator consumers. Preserve local editing/scheduling resources and canonical turn/queue admission fences. Coordinate accepted-source and lifecycle semantics with Arendt; no competing lifecycle edits.

The AST inventory is lexical evidence, not dynamic receiver resolution. Textual data_bind/getters, generated partialmethod actions and inherited methods require source reading; no resolved-call claim is made for them. Installed SDK schema imports are recorded but its complete source-root census remains outstanding before boundary closure. Native provider activity is independent concurrency and is not deleted as a competing UI authority.

## Final validation only

After coherent implementation and after-source declaration/consumer output, use one focused sanity batch and one installed application journey for actual keyboard/click availability, ordinary/immediate/empty queue dispatch, refusal, local composer and retired attachment behavior. No public/uncertain input replay. The completed304 receiving journey and raw negative oracle evidence remain unchanged.
