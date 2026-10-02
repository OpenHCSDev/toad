# T4 canonical ACP selection ownership

## Semantic scope and current owners

Source analysis precedes implementation; validation runs after the coherent caller closure.

- AgentConfiguration and its existing ConfigurationSetting family own SDK configuration advertisements and accepted model/thinking selections. A requested picker value is pending intent until the original ACP response or notification is accepted.
- AgentController owns ACP mode advertisement/current selection; CurrentModeUpdate already reaches it. Mode is not the Toad application tab mode or the editor's shell mode.
- Conversation, Prompt and ModelSwitcher currently retain independently writable catalogs/current selections used for command availability, option highlighting, model labels and model-history recording. These are competing copies, not renderer resources.
- Existing option lists, search text, highlighted navigation, recent-use records, drafts and undo are presentation/editor resources and remain owned by those resources.

## Complete caller closure

Producer/read families: AgentConfiguration/ConfigurationSetting, AgentController, AgentSession.publish_configuration/set_mode, SessionUpdateEffect.

Consumers: Conversation compose/change-model/change-mode/turn-over/model-info publication, Prompt label/mode list/model picker, ModelSwitcher catalog/filter/current marking, ModelCommand, ModeSwitcherAction, MainScreen ModeProvider, CommsChat composer, and affected installed pilots.

Extend the existing owners and publish invalidation of those original resources. Remove copied view fields and value-carrying selection messages together. Session replacement and detached/returned surfaces must derive the actual current owner; request errors must not promote requested intent to accepted selection.

## Final qualification

After source closure, one focused sanity batch and an installed ACP/UI journey covering advertised modes/models, acknowledged selection, unsolicited source updates, refused selection, and A/B/A return. Existing real application and ACP paths are required; no UI substitute or selection-state mirror.

No observed lost controller update or provider failure is claimed. This scope does not alter native budgets, bus readers, cursor custody or viewport preparation.

## Working implementation

- ConfigurationSetting derives its selected **original SDK choice**; the separate Model tuple conversion is deleted. AgentConfiguration publishes only an invalidation carrying its original Agent, not a second catalog/current-value record.
- AgentController keeps one original SDK SessionModeState. Full advertisements, unsolicited CurrentModeUpdate and acknowledged set-mode requests use the same mode-state admission. There is no second controller table/ID pair. Session replacement and process startup clear those advertisements through the existing controller lifecycle.
- Conversation and Prompt no longer own models/modes/current_model/current_mode/thinking_level; ModelSwitcher no longer owns models/current_model_id. All consumers listed above now read the original owners. Prompt's Agent reference is the original resource binding; option-list items and rendered label Content are presentation resources, never admission or selection authority.
- Picker request values remain local request intent until the actual ACP response; original ClientSessionRequest fences the response against session/process replacement. Refused requests do not alter accepted values. Model-history recording retains the existing recency meaning: accepted selection on acknowledged selection/completed turn, not proof of which model a provider used internally.
- Four copied-value message classes and their independent view writers are deleted. One resource invalidation refreshes rendering and action bindings. Existing ConfigurationSetting subclasses still declare advertisement membership; no new selection family, registry or mirror was introduced.

## Qualified installed checkpoint

Production 85115f155d17ae8c5b05b512df8ecf5bd9a6aacb deletes 238 lines and adds 184 across 14 production files. Four copied-value classes and every listed reader/writer are removed. The final debt census adds zero dispatch, foreign absence, long boolean chain or codec-subclass debt; class definitions decrease by four. Existing optional SDK advertisements remain optional.

Normal noneditable 69-package installation verifies the complete 306-file Toad and 329-file Core inventories, declared Textual source and unchanged full-trusted Native5. Four focused checks pass. The installed SDK/stdio/UI journey passes mode advertisement and acknowledged update, filesystem, permission, terminal and reply presentation.

The configured 42,932,905-byte helper source uses one canonical saved fork and one private root. Fresh launch capture matches public PID 3085175/start 39028411 and the approved current default interpreter. The same owned fixture is explicitly reopened after its deliberate teardown; ensuring-load cannot undo a stopped owner.

Actual model-picker/thinking HIGH clicks and acknowledgements, invalid-request preservation, physical A/B/A with original Agent/draft/undo and current-row marking pass. Reconnect restores canonical configuration and paints it. Qualification is recorded in bounded continuations: 04 ends after positive selector checks on a tab-query driver failure; 05 proves A/B/A before an early paint assertion; 06 checks only the missing reconnect/paint boundary and exits zero. Raw failures remain preserved. This is not a claim that the first driver ran uninterrupted.

Configured current OFF remains reportable although the native discovered choices reject OFF as a new request. That distinction belongs to the existing configuration admission owner; this frontend change does not override it. HIGH is a distinct authorized private-child choice.

Zero native input rows, zero provider prompts, unchanged auth/settings hashes, retired private owner and still-live original public owner are verified. No public restart, source change or uncertain-input replay occurs. Receipts live in `evidence/canonical-agent-selections-302/`; the complete inventory and raw logs remain under the named protected `.artifacts/` paths.

The separate Prompt native action availability/submit-now backlog is not closed by this model/mode work. No native budget, provider-compaction or broad performance claim is made.
