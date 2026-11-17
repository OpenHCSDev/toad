"""Shared menu-item source for sidebar relationship/conversation rows.

The one place both frontends read the row menu's labels + runs from. Previously
Textual's `widgets/thread_comms.show_row_menu` handrolled
`[(open_fn, "Open"), (copy_fn, "Copy name")]` inline, and Qt's
`ConversationRow.held_actions` returned `()`, so the two menus diverged — Tristan
could long-press on Textual and get Open/Copy, long-press on Qt and get nothing.
The polymorphism rule is "two items that must stay the same live in one owner":
this module IS that owner for the base row menu.

Row-specific commands (view-local commands via `CommandCatalog`) already pass
through `widgets/sidebar_tree.TargetMenuTree.show_row_menu` which is already
polymorphic via `row_menu_context(row)`. This helper covers the simpler
Open/Copy case that shares no catalog.
"""

from __future__ import annotations

from collections.abc import Callable

from toad.client.menu_entry import MenuEntry


def menu_entries_for_row(
    target_name: str,
    *,
    copy: Callable[[str], object],
    open_callback: Callable[[], object] | None,
) -> tuple[MenuEntry, ...]:
    """Open/Copy entries for a sidebar conversation row.

    `open_callback=None` means the row is currently unopenable (Textual's
    `row.available == False`). `copy` is the clipboard callback from whatever
    object owns it (Textual app, Qt app) — a bare function kept toolkit-neutral
    so the helper itself doesn't import either frontend.
    """
    items: list[MenuEntry] = []
    if open_callback is not None:
        items.append(MenuEntry(label="Open", run=open_callback))
    items.append(MenuEntry(label="Copy name", run=lambda: copy(target_name)))
    return tuple(items)
