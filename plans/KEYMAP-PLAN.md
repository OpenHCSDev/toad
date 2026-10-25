# Keymap plan: one declaration per binding, modes as a family, the menu as a view

Toad main **6a573c4b4** (after #1209). Textual fork: the `OpenHCSDev/textual` main that Toad pins in
`pyproject.toml:42`, read from runtime core-f23ca8968 (`textual/document/_editing.py`, 569 lines).
Tristan, 2026-10-24: "proper inheritance polymorphism maxing so we can have a proper keybinding menu ...
we should not manually expose everything we should automatically expose everything it should cover vim mode".

This plan writes no source. Its surfaces are dispatched as orders, one owner each.

## The defect in one sentence

A key's binding, its name and whether anyone can see it are declared in four systems and five spellings,
so no menu can list what Toad does without a hand roster, and vim keys exist twice.

## Evidence (AST inventory of `src/`, every row read in the code)

| What | Count | Where |
|---|---|---|
| Raw `BINDINGS` class attributes | 64 | 64 classes; e.g. `screens/main.py:212`, `screens/comms.py:38`, `widgets/prompt.py:239` |
| `Binding(...)` calls with a string action name | 98 | 12 key-to-action pairs are repeated 41 times (table below) |
| `action_*` methods named by strings | 145 | dispatched by Textual's string names (MEMB-4) |
| Toad's declared action classes with a `key` | 39 | `KeyboundAction` (`widget_actions.py:12`) on 4 `ACTIONS` owners: `app.py:132`, `widgets/conversation.py:793`, `widgets/prompt.py:220`, `widgets/question.py:123` |
| `on_key` handlers comparing key literals | 6 | `widgets/conversation.py:936`, `widgets/prompt.py:355`, `screens/store.py:551`, `widgets/side_bar.py:773`, `widgets/terminal.py:378`, `widgets/menu.py:115` |
| App-level vim actions | 12 | `application_actions.py:198-279` (11 `VimNavigationAction` members) plus `VimHintsAction` (`widget_actions.py:88`) |
| Editor-level vim commands (Textual fork) | 22 | `EditorCommand` family, `_editing.py:206`; 26 `keys = (...)` tuples |
| Reads of the `vim_keys` flag | 4 | `conversation_actions.py:50`, `widget_actions.py:85`, `widgets/prompt.py:339`, `setting_effects.py:57` |
| Opt-in exposure markers | 7 `show = True`, 3 `show=True`, 39 `show=False`, 6 `PaletteAction`, 4 `MenuAction`, 6 `menu_order` | `application_actions.py`, `widget_actions.py:33` |
| Hand-written human names per action | 17 `description`, 11 `tooltip`, 20 `help`, 7 `label()`, 6 `menu_label` | `application_actions.py`, `conversation_actions.py`, `prompt_actions.py` |
| `Binding.id` or `App.set_keymap` use | 0 | Textual 8.2.8 ships both (`textual/binding.py:89`, `textual/app.py:4094`) |

Repeated bindings (one fact, 41 copies, IMPL-12):

| Pair | Copies | Sites |
|---|---|---|
| `escape -> dismiss` | 7 | `comms_menu.py:58`, `menu.py:40`, `model_switcher.py:85`, `path_search.py:151`, `prompt.py:80`, `prompt.py:576`, `slash_complete.py:60` |
| `up -> cursor_up`, `down -> cursor_down` | 6 + 6 | `comms_sidebar.py:171-172, 312-313`, `grid_select.py:17-18`, `model_switcher.py:82-83`, `path_search.py:140-143`, `slash_complete.py:45-52` |
| `enter -> submit` | 3 | `model_switcher.py:84`, `path_search.py:150`, `slash_complete.py:59` |
| `enter -> select`, `space -> launch` | 3 + 3 | `store.py:170, 176, 301, 302`, `grid_select.py:21`, `agent_modal.py:34` |
| `ctrl+g -> toggle_irc` | 3 | `screens/comms.py:41`, `screens/main.py:213`, `screens/welcome.py:201` |
| `ctrl+[ / ctrl+] -> session_previous / session_next` | 2 + 2 | `screens/comms.py:43, 49`, `screens/main.py:216, 223`; `SESSION_NAVIGATION_GROUP` is declared twice too |
| `tab / shift+tab -> app.focus_next / previous` | 2 + 2 | `screens/permissions.py:50, 58`, `screens/store.py:329, 335` |
| `enter,space -> activate` | 2 | `side_bar.py:250, 508` |

## Findings

Each finding is stated as: pattern, the fact, where it is restated (at), the mechanism that should derive it, and where that mechanism lives (by).

1. **IMPL-13, one mechanism at three levels of rigour.** Fact: which key runs which action.
   At: raw `BINDINGS` with string action names (64 classes); `KeyboundAction` classes (39); `EditorCommand.keys` (22).
   Derive: one declared action family whose members carry their keys.
   By: `widget_actions.py:12` `KeyboundAction`, which already projects a member to a Textual `Binding` (`widget_actions.py:22-27`). Two thirds of the bindings never adopted it.
2. **IDEN-3 and IDEN-4, one action named five ways, and the copies already disagree.** Fact: the human name and summary of an action.
   At: `QuitAction` (`application_actions.py:130-140`) has `menu_label = "Exit"`, `description = "Quit"`, `label() -> "Quit"`, plus a `tooltip` and a `help` saying the same thing twice. `SettingsAction` (`:71-80`) has `menu_label`, `description` and `label()`, all "Settings".
   Derive: one title on the declaration. The class docstring is the summary.
   By: the action class (new field on the family root).
3. **MEMB-2, exposure is a hand roster per surface.** Fact: which actions a user can discover.
   At: the footer reads `show` (49 hand flags). The palette reads the `PaletteAction` mixin (6 members, `application_actions.py:26`). The sidebar menu reads `MenuAction` (4 members, `widget_actions.py:33`). Textual's `HelpPanel` reads only the focused chain's `BINDINGS`. An action is invisible unless someone remembers each opt-in.
   Derive: every declared action is exposed. The surfaces are views over one registry. Hiding is the exception, declared once (`System`, for instance).
   By: the family registry filled at `__init_subclass__` (`agent_comms.declared_family.DeclaredFamily`, already the root of `ApplicationAction`).
4. **Hand-numbered ranks.** Fact: menu order.
   At: `menu_order = 0/10/20/100` (6 sites: `application_actions.py:34, 72, 131`; `comms_transfer.py:66, 89, 107`).
   Derive: declaration order in the registry.
   By: `DeclaredFamily` registration order.
5. **IMPL-10 and IMPL-1, the vim mode encoded as a bool and a string.** Fact: which key set is live.
   At: `VimApplicationAction.available` tests `settings.ui.vim_keys and app.current_mode == "workspace"` (`widget_actions.py:84-85`). `CancelAction.vim_profile` plus `VimCancelAction` (`conversation_actions.py:47-62`) picks a key by comparing a bool on the action with the setting. `apply_keyboard_profile` picks `VimInsert() if enabled else EditingMode()` (`widgets/prompt.py:339-341`).
   Derive: a `KeyMode` family. The setting decodes once into a member, and each member owns its keys and its editor mode.
   By: new `KeyMode` root, created by surface K4.
6. **IMPL-12 and forwarding, app vim as a second copy of existing actions.** Fact: what `j k h l ctrl+d ctrl+u` do.
   At: 11 `VimNavigationAction` classes (`application_actions.py:198-279`), each a one-line forwarder to an existing Textual action (`window.action_scroll_down`, and so on).
   Derive: the existing scroll actions declare their vim-mode keys. The forwarders are deleted.
   By: the scroll owner's action family (the conversation window).
7. **MEMB-1 / MEMB-3, keys handled outside any binding.**
   - `store.py:556` holds a `LAUNCHER_KEYS = "123456789abcdef"` literal.
   - `store.py:345` restates the same set as `key_display="1-9 a-f"`.
   - `side_bar.py:774` hard-codes `/`.
   - `prompt.py:356-358` hard-codes tab and escape.

   None of these can appear in a menu. By: launcher slot actions whose keys derive from slot index (one declaration), and a focus-search action.

   Two sites are the external contract and stay, renamed to say so: `terminal.py:378` passes keys through to a child process, and `conversation.py:936` routes printable text to the prompt (text input, not bindings).
8. **MEMB-4, string action names.** 98 `Binding("key", "action_name")` calls and 145 `action_*` methods tie keys to strings. `NativeAction.binding_name` (`widget_actions.py:50-52`) already derives the Textual name from the class (`FieldCodec.encode`). The raw calls bypass it (BOUND-2).
9. **A live conflict the inventory surfaced.** `f2` is `SettingsAction.key = "f2,ctrl+comma"` (`application_actions.py:74`) and also `Binding("f2", "commander_page")` (`screens/main.py:215`). Textual resolves it by screen precedence, so Settings is unreachable by `f2` on the main screen. Nothing reports it, because no single owner can see both declarations.

## Target

1. **One action family root**, `Action(DeclaredFamily)`, in `widget_actions.py`. It merges `NativeAction` and `KeyboundAction`.
   - Each member declares `title` once, and its docstring is its summary.
   - It declares `keys: ClassVar[KeyMap]`: a mapping from `KeyMode` members to key strings, so one member owns its default and its vim keys.
   - It owns `available` and `apply`.
   - `label()` survives only as an override, for state-dependent titles such as the toggles at `:161` and `:119`.
2. **`KeyMode` family**, with members `Standard`, `VimNormal`, `VimInsert` and `VimVisual`.
   - The `vim_keys` setting decodes once, at the settings boundary, into the active member.
   - Each member answers which of an action's keys are live, and which Textual-fork `EditingMode` the prompt takes. That deletes `vim_profile`, `VimCancelAction`, the `vim_keys` reads at 3 sites and the `"workspace"` string compare. Workspace-only actions move to `WorkspaceScreen`'s `ACTIONS`.
3. **Capability mixins carry the shared bindings once**: `Dismisses` (escape), `MovesCursor` (up/down), `Submits` (enter), `Selects` (enter), `Launches` (space), `CyclesFocus` (tab/shift+tab), `CyclesSessions` (ctrl+[ / ctrl+]) and `TogglesIrc` (ctrl+g). Each of the 41 copies becomes a parent class on its widget.
4. **Textual is the external contract below one projection.** `DeclaredWidgetActions.__init_subclass__` (`widget_actions.py:98-110`) stays the only producer of `BINDINGS` and `action_*`. Each `Binding` gets `id = declared_name`. Remapping is one owner, a `Keymap` preference decoded once and applied through `App.set_keymap` (`textual/app.py:4094`). No widget writes `BINDINGS`, `Binding(` or `action_*` by hand.
5. **The editor's vim family joins the same registry.**
   - In the Textual fork, `EditorCommand` gains `title`, and registers at `__init_subclass__` instead of walking `__subclasses__()` and decoding by linear search (`_editing.py:209-217`).
   - Its keys stay keyed by `VimNormal`.
   - A shared base for "a declaration with keys and a title" lives in the Textual fork, the lowest repo, and Toad's `Action` derives it. One ABC, no Protocol.
6. **The keybinding menu is a pure view.**
   - One screen lists every member of the shared base, grouped by owning family (app, screen, widget, editor), with one column per `KeyMode`, availability shaded from `available()`, and the summary from the docstring.
   - The footer, the palette, the sidebar menu and the help panel become filters over the same registry.
   - A new action appears in all of them with zero view edits.

Textual's own mechanism ends at `Binding`, `check_action`, `run_action`, `HelpPanel` and `set_keymap`. Everything above that line (identity, title, mode, exposure, menu) is ours, and it is declared once.

## New-case test

| Change | Edits today | Edits after |
|---|---|---|
| Add one app action with a key, visible in footer, palette, menu and help | 6: class, `key`, `description`, `show`, `PaletteAction` + `label` + `help`, `MenuAction` + `menu_order` + `menu_label` | 1: the class (title, keys, apply) |
| Add a vim key to an existing action | 2: a forwarding `Vim*Action` class plus its `available` check | 1: one entry in the action's `keys` |
| Add an editor motion and show it in the menu | impossible today: `EditorCommand` has no title and no registry the menu can read | 1: the `Motion` subclass |
| Give a new picker widget escape, up, down and enter | 4 `Binding(...)` lines plus 4 `action_*` methods, copied | 0: add parents `Dismisses, MovesCursor, Submits` |
| Let the user remap a key | impossible: no `Binding.id` anywhere | 0 code: one `Keymap` preference row |

## Surfaces and waves

The crossings were checked against the open Toad PRs at 6a573c4b4: #1211 touches only tests/textual, #1207 only `db.py` and #1202 one test. None touches these files.

| Wave | Surface | Files | Deletes |
|---|---|---|---|
| 0 | **K0 guard.** A test fails on: `BINDINGS =`, `Binding(` or `def action_` outside `widget_actions.py`; a key literal compared in `on_key` outside the two contract sites; a `vim_keys` read outside `KeyMode`; and `menu_order`. It starts as a ratchet at today's counts (64 / 98 / 145 / 6 / 4 / 6) that can only fall. | `tests/guards/test_keymap_owner.py` (new) | none |
| 1 | **K1 family root.** `Action` merges `NativeAction` and `KeyboundAction`. `title` plus the docstring replace `description`, `tooltip`, `help` and `menu_label`. `Binding.id` derives from the declared name. Exposure defaults to on, and `System` hides. | `widget_actions.py`, `application_actions.py`, `conversation_actions.py`, `prompt_actions.py`, `question_actions.py` | `MenuAction`, `PaletteAction`, `menu_order` ×6, 54 name strings |
| 1 | **K5 editor registry.** `EditorCommand` registers at `__init_subclass__` and gains `title`. The shared keyed-declaration base goes in. | OpenHCSDev/textual `document/_editing.py`, `binding.py` | the `__subclasses__` walk and the linear `decode` |
| 2 | **K2 capability mixins.** Each of the 12 repeated pairs is declared once. | the 20 widget files in the table | 41 `Binding` copies and their `action_*` bodies |
| 2 | **K4 `KeyMode` family.** Vim keys live on the actions. | `widget_actions.py`, `application_actions.py:198-279`, `conversation_actions.py:47-62`, `widgets/prompt.py:337-341, 869-880`, `setting_effects.py:57`, `preferences.py:72` | 11 forwarders, `VimCancelAction`, `vim_profile`, 3 flag reads, the `"workspace"` compare |
| 3 | **K3 migration.** The remaining raw `BINDINGS` and `action_*` move onto their owners' families, screen by screen. The `f2` conflict is resolved by one owner. | the remaining raw `BINDINGS` classes (64 minus those K2 absorbs) | every hand `Binding(` and `def action_` |
| 3 | **K6 key literals.** Launcher slots and search focus become actions. | `screens/store.py:345, 551-562`, `widgets/side_bar.py:773-777`, `widgets/prompt.py:355-359` | `LAUNCHER_KEYS`, the `key_display="1-9 a-f"` copy |
| 4 | **K7 menu and remap.** A keymap screen over the registry. Footer, palette and sidebar menu become filters on it. The `Keymap` preference goes through `set_keymap`. | `screens/keymap.py` (new), `widgets/side_bar.py:343`, `application_actions.py:282-305`, `preferences.py` | `ApplicationCommands`' separate roster walk |

Done means K0's ratchet reads zero on every count except the two named contract sites. The real app must show:
- the keymap screen listing every action, including the editor motions;
- vim mode toggled in Settings, changing the live keys without a restart;
- one remapped key surviving a restart.

## Owner questions (each has a default)

1. **Remapping in this plan or later?** Default: in it (K7). `set_keymap` exists, so the cost is one preference row.
2. **Does the menu replace Textual's `HelpPanel` (F1) or sit beside it?** Default: replace. F1 opens the keymap screen filtered to the focused widget, so one view serves both.
3. **Which key wins F2, Settings or the commander page?** Default: the commander page keeps `f2`, and Settings keeps `ctrl+comma`. #1198 made F2 the commander page.
4. **Are vim app-level keys live on every screen or only the workspace?** Default: the workspace only, as today, now declared by `WorkspaceScreen`'s family instead of a string compare.

## Assumed

- The Textual fork read from runtime core-f23ca8968 matches the `OpenHCSDev/textual` main that Toad pins. Surface K5's owner re-reads it at dispatch.
- The 145 `action_*` methods include Textual-inherited overrides that some widgets need (for example `action_cursor_up` on lists). K3 classifies each one before moving it.
- The `conversation.py:936` printable router and the `terminal.py:378` passthrough are text and child-process input, not bindings.
