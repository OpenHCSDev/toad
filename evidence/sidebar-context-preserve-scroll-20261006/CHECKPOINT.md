# Preserve sidebar position when opening a pointer menu

## Existing owner and complete path

`CommsSidebar.on_click` handles button 3, resolves the actual native row under the pointer and calls `CommsRow.show_menu`. That method previously focused any row without an open mode. Native `Widget.focus` defaults `scroll_visible=True` and passes it to `Screen.set_focus`, so opening a pointer menu could scroll its sidebar before command discovery finished.

The menu already receives the exact original `NavigationTarget`, mode and channel. `TargetContext.show_menu` retains the selected screen/source, discovers commands and publishes the original `ContextMenu`; no command reads row focus to choose its target. Both thread and channel rows share this path. Keyboard traversal remains with `TargetTree.action_cursor_up/down`, its cursor, row focus and `scroll_visible`. Pointer rows already declare `focus_on_click=False`.

## Change

Delete the extra row focus from `CommsRow.show_menu`. Pointer menu opening now leaves original focus and scroll custody alone. No stored scroll mirror, restoration callback, special-case menu, timer or backend change was introduced.

## Checks and remaining acceptance

AST comparison against actual main shows only `CommsRow.show_menu` changed. Compilation without imports and diff check pass. Native menu selection, command discovery and keyboard traversal are unchanged.

A standalone source App import was refused before App construction because this shell lacks the ACP dependency. Trying the existing Kimi dependency exposed its Python 3.13 compiled dependency mismatch with system Python 3.14; no App, process, provider, prefix write or input ran. No import fallback or environment installation was added. Actual mounted/installed right-click verification remains required: with a partially visible unopened row, right-click it, inspect its menu, dismiss, and confirm the same left-sidebar position, selected session and editor; repeat for an open row and keyboard navigation.

Parent owns that acceptance together with the current physical gesture trace. Physical02 is independently closed and its original evidence remains immutable. This source repair does not reopen it or claim live deployment.
