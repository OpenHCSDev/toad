"""Textual-facing: a right-click draws exactly the element's declared menu, and nothing of its
own (`TargetLine.menu_entries`, `TabElement.menu_entries`). Qt's `menu_parity` drive checks
Qt draws the same declared entries for the same elements; `tests/model/test_menu_owners.py`
keeps either toolkit from building its own."""
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_tabs import SessionLabel


def drawn(app) -> list[str]:
    options = app.screen.options
    return [str(options.get_option_at_index(index).prompt) for index in range(options.option_count)]


async def right_click_menu(ui, widget) -> list[str]:
    app, pilot = ui.textual
    widget.scroll_visible(animate=False)
    await ui.step()
    assert await pilot.click(widget, button=3)
    await ui.until(lambda: isinstance(app.screen, ContextMenu), why="the element's menu")
    labels = drawn(app)
    await pilot.press("escape")
    await ui.until(lambda: not isinstance(app.screen, ContextMenu), why="the menu to close")
    return labels


async def test_sidebar_lines_and_tabs_draw_their_declared_menus(workspace):
    workspace.thread("owner", "team", title="Menu parity")
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        sidebar = app.workspace_chrome.channels
        if sidebar.collapsed:
            sidebar.toggle()
        tree = sidebar.query_one(CommsSidebar)
        await ui.until(lambda: "#team" in tree.groups and tree.groups["#team"].member_container.is_mounted,
                       why="the #team group")
        group = tree.groups["#team"]
        if not group.expanded:
            group.toggle_members()
        await ui.until(lambda: "owner" in group.rows and group.rows["owner"].is_mounted, why="the owner line")

        thread = group.rows["owner"]
        thread_menu = await right_click_menu(ui, thread)
        assert thread_menu == [entry.label for entry in await thread.menu_entries()]
        # The target's own commands, not the relationship row's Open / Copy name.
        assert thread_menu and thread_menu != ["Open", "Copy name"]

        channel = group.row
        channel_menu = await right_click_menu(ui, channel)
        assert channel_menu == [entry.label for entry in await channel.menu_entries()]
        assert channel_menu

        tab = next(label for label in app.query(SessionLabel)
                   if label.mode_name == app.selected_mode)
        tab_menu = await right_click_menu(ui, tab)
        assert tab_menu == [entry.label for entry in tab.menu_entries()]
        assert tab_menu[-1] == "Close tab"
