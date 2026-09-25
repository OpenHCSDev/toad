# Shared discovery for context menus and slash commands

## Status and ownership

Draft handoff requested by the user on 2026-09-25. This PR contains the
investigation and implementation task only. No runtime fix or validation of a
fix is claimed. The user's comms agent will implement the change on this branch
and update this PR. No other implementation is in progress from this handoff's
author.

Investigation base: Toad `325356a22eeba95eb61c7dac3b1ba31bd8a249fa`.

## User-visible problem

Right-click menus expose actions that do not appear when the user types `/` in
the input box. Available operations should be discoverable through both
interfaces where their target context applies.

## Confirmed code paths

- `src/toad/widgets/conversation.py`: `_build_slash_commands()` maintains a
  built-in list and appends ACP-advertised commands. `slash_command()` dispatches
  the built-ins separately. The backend context-action catalog is absent from
  this discovery path.
- `src/toad/widgets/comms_sidebar.py`: `_show_thread_menu()` derives thread
  actions from `agent_comms.context_tool_catalog("thread")`, applies status
  filtering, then adds copy, pin and close-view actions. `_show_channel_menu()`
  assembles channel pinning, any-mode, mark-read and copy actions separately.
- The backend owns the thread tool declarations in
  `agent_comms.tools.ToolDeclaration`, including labels, order, parameter schemas
  and `context_bindings`. These already declare fork, start, stop, archive,
  delete and mark-read operations.
- `src/toad/app.py`: `invoke_thread_action()` and `_run_thread_action()` own
  asynchronous UI dispatch, pending feedback, error reporting and reconnects.
  Mark-read deliberately uses `mark_user_view_read()` here; preserve that
  user-view meaning rather than substituting the model's inbox ACK operation.
- `src/toad/screens/comms.py`: `on_thread_action()` handles fork parameters using
  `ForkDialog`. Reuse that interaction through a shared dispatch path, including
  ordinary agent views.
- `src/toad/widgets/comms_chat.py`: `CommsChatView` inherits `Conversation` but
  overrides submission and uses `ChannelPrompt` for channels. Check this path
  explicitly; adding completion entries to `Conversation` alone is insufficient.
- `src/toad/widgets/comms_menu.py` builds and dispatches the visible menus.

## Implementation contract

1. Derive menu entries and slash suggestions from the same applicable action
   declarations. Backend operations retain backend-owned names, descriptions,
   schemas and bindings. Toad-owned actions have one declaration at their UI
   owner. Avoid another manually maintained copy of backend operations.
2. Use one dispatch path for each action across both interfaces. Preserve the
   existing parameter dialogs, pending feedback, validation and errors.
3. Resolve the target from the current thread/channel/view context. Make an
   explicit target selection available where needed. Never silently act on a
   different thread because the sidebar selection and open conversation differ.
4. Apply the same availability rules to menus and slash discovery. Preserve
   running/stopped/archived rules, exact-channel any-mode applicability, channel
   membership needed for pinning, and view identity needed for close-view.
5. Read current backend state when validating execution. Refresh discovery when
   context or state changes; do not introduce a second UI state authority.
6. Preserve existing slash commands and ACP-advertised commands. Define collision
   handling explicitly so a displayed action cannot dispatch a different command.
   Commands handled locally must not become prompts sent to a model.

## Acceptance checks

- Mounted agent, DM and channel views: every applicable right-click action is
  discoverable through `/`, with matching label/help and target semantics.
- Choosing the same action through either interface reaches the same handler
  once. Fork uses the same dialog; canceling it produces no operation.
- Cover running, stopped and archived threads, context changes, rename, and
  state changes between opening completion and execution. Existing backend
  validation still decides whether an operation is allowed.
- Channel pinning, member pinning and any-mode have the correct scope; mark-read
  retains user-view semantics. Discovery itself never acknowledges messages.
- A declaration added to the backend context catalog becomes discoverable
  without editing a second command list. Existing ACP commands remain usable.
- Exercise actual input submission as well as list construction. Use isolated
  test wires and mounted Toad; no live messages, provider calls or destructive
  operations against the user's threads.

Use focused local checks and record their results in the PR. CI can run
asynchronously. Keep the PR draft until implementation and review are complete.
