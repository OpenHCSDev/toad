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
