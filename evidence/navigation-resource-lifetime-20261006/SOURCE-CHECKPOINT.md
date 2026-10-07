# Navigation and completion resource lifetime

Base: current main 91386035c. No wheel, pin, native, provider or live-prefix change.

## Source reason and complete consumer change

| Fact / resource | Existing owner | Consumer change |
| --- | --- | --- |
| Current route and admitted Comms service | CoordinationAccess.require; RouteSelection | SessionAdmissions.retire_missing borrows this service instead of constructing Comms on every observation. The original registry store retains its decoded document. Joined results must still match the current route and observed service. |
| Original hidden admission and thread birth | NativeSessionAdmission / HistorySessionAdmission; ThreadIncarnation.current | Existing member, alias, birth and channel-removal predicates are unchanged. Failed acquisition retains the view. Native launch's original-root alias lookup remains distinct. |
| Selected prompt display | SessionView.is_current | Conversation refreshes only the selected prompt; selection refresh is declared through existing event dispatch. CommsChat's overriding selection consumer delegates that refresh. A query finishing after deselection cannot bind its display result. |
| Popup opening and dismissal | PromptPopup.is_open | SlashComplete owns demanded catalog refresh and filters rows only while open. Hidden Mount row construction is deleted. Coordination observations refresh an open popup, not every closed prompt. |
| Plain slash and highlighting | Prompt.slash_commands; CommandText.decode_input | Initial setup, ACP advertisements, selection and explicit refresh retain the original display declarations. Typing slash opens the popup and requests live applicability. Closed display declarations are not execution authority. |
| Applicability and execution | TargetContext / CommandCatalog | Demand reads still use the original read worker and route checks. CommandCatalog.execute always reacquires live choices; ContextualCommand.apply rebinds its original target. No new catalog cache or registry. |

The source trace covered all update_slash_commands, command_target_context,
available_actions, target_catalog and retire_missing consumers, plus Prompt,
PromptTextArea, CompletionPopup, SlashComplete and the nominal event carrier.
Before-change production Package: 288 modules, zero parse omissions. Dynamic
widget attachment and service replacement are runtime relationships, not proven
by AST; original checks remain explicit.

## Actual affected App check

Runner: tests/navigation_resource_lifetime_pilot.py. Existing private source
ToadApp/runtime_fixture and source dependencies; no mocks or provider inputs.
Final result: /home/ts/.cache/agent-scratch/hnr05/app/result.json.
Four admitted native views; repeated idle observations made no service
constructions, registry decodes, action queries or OptionList rebuilds. Hidden
prompt refresh skipped acquisition; selected prompt refreshed. Native slash
entry opened populated choices; Escape dismissed them and preserved slash text.
Rename retained the original birth; genuine deletion and same-name replacement
retired its hidden admission. An unavailable route retained hidden admissions.
Original test context owns daemon/child cleanup; the runner joined.

Earlier negatives remain under hnr01, hnr02.log and hnr03. My first deletion
control incorrectly treated unregister as removal; it only stops the original
thread. The corrected control uses Registration.delete_originals before a new
declaration. hnr02 failed before App import because old uv paths were removed;
verification reuses the existing source environment, with no install.
hnr04 passed; hnr05 verifies the final declaration-dispatch and selected-result
binding changes. No failure was presented as an application retirement defect.

This establishes private headless behavior, not installed tree-toggle latency,
physical frame time or total CPU improvement. Parent owns integration and live
delivery/measurement. Original profile and previously accepted selection,
retained-sidebar, configured and loaded receipts are unchanged.
