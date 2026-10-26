"""Workspace navigation keys operate original tabs; editors retain typed capitals."""

from toad.preferences import SETTINGS
from textual.command import CommandPalette
from textual.widgets import Input, OptionList
from toad.widgets.comms_menu import ContextMenu
from toad.application_actions import (
    VimCycleTabAction, VimHistoryAction, VimSidebarAction, VimMoveTabAction,
    VimHistoryBackAction, VimHistoryForwardAction,
)
from toad.widgets.side_bar import SideBar, SidebarAction


async def test_history_tab_selection_and_persisted_reorder_keep_original_tabs(workspace):
    async with workspace.app(size=(130, 42)) as ui:
        app, pilot = ui.textual
        app.saved_settings.set(SETTINGS.ui.vim_keys, True)
        first = ui.selected_tab
        await ui.press('escape')
        second = await ui.new_session()
        await ui.press('escape')
        third = await ui.new_session()
        await ui.press('escape')
        originals = app.tab_order.names

        # Commands stay available from Insert even though their keys belong to
        # editing. Execute history-back through the actual menu in that state.
        await ui.press('i')
        assert ui.conversation.prompt.prompt_text_area.editing_mode.accepts_text
        # The menu and palette offer configured leaves, not shared family bases.
        assert await pilot.click('#main-menu')
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why='the application menu')
        options = app.screen.options
        actions = [options.get_option_at_index(index).action for index in range(options.option_count)]
        bases = {VimCycleTabAction, VimHistoryAction, VimSidebarAction, VimMoveTabAction}
        assert not bases.intersection(type(action) for action in actions)
        options.highlighted = next(index for index, action in enumerate(actions)
                                   if type(action) is VimHistoryBackAction)
        await ui.press('enter')
        await ui.until(lambda: ui.selected_tab == second, why='menu history-back action')

        await ui.press('ctrl+p')
        await ui.until(lambda: isinstance(app.screen, CommandPalette), why='the command palette')
        app.screen.query_one(Input).value = 'Vim'
        options = app.screen.query_one(OptionList)
        def palette_labels():
            return [options.get_option_at_index(index).hit.text for index in range(options.option_count)]
        await ui.until(lambda: VimHistoryForwardAction.title in palette_labels(), why='Vim palette commands')
        assert not {'Vim cycle tab', 'Vim history', 'Vim sidebar', 'Vim move tab'}.intersection(palette_labels())
        app.screen.query_one(Input).value = VimHistoryForwardAction.title
        await ui.until(lambda: palette_labels() == [VimHistoryForwardAction.title],
                       why='the exact forward command search result')
        await ui.press('enter')
        await ui.until(lambda: ui.selected_tab == third, why='palette history-forward action')
        assert ui.conversation.prompt.prompt_text_area.editing_mode.accepts_text
        await ui.press('escape')

        async def navigate(key, expected):
            editor = ui.conversation.prompt.prompt_text_area
            assert editor.has_focus and editor.editing_mode.allows_application_commands
            await ui.press(key)
            await ui.until(lambda: ui.selected_tab == expected, why=f'{key} selects its original tab')
            await ui.until(lambda: ui.conversation.prompt.prompt_text_area.has_focus,
                           why='the destination editor retains focus')
            assert ui.conversation.prompt.prompt_text_area.editing_mode.allows_application_commands

        await navigate('H', second)
        await navigate('H', first)
        await navigate('L', second)
        await navigate('L', third)
        await navigate('J', second)
        await navigate('K', third)

        # These same characters are text in insert mode, not navigation commands.
        editor = ui.conversation.prompt.prompt_text_area
        ui.conversation.prompt.enter_insert()
        await ui.press('H', 'J', 'K', 'L')
        assert editor.text == 'HJKL'
        assert ui.selected_tab == third
        assert app.tab_order.names == originals
        await ui.press('ctrl+shift+k')
        assert editor.text == ''
        assert ui.selected_tab == third and app.tab_order.names == originals
        await ui.press('H', 'J', 'K', 'L')

        await ui.press('escape')
        assert editor.has_focus
        await ui.press('ctrl+shift+j')
        moved = (originals[0], originals[2], originals[1])
        await ui.until(lambda: app.tab_order.names == moved, why='the selected tab moves left')
        assert ui.selected_tab == third
        assert tuple(tab.identity for tab in app.session_navigation.tabs) == moved
        database = await app.get_db()
        assert tuple(row.identity for row in await database.tab_list()) == moved
        await ui.press('ctrl+shift+k')
        await ui.until(lambda: app.tab_order.names == originals, why='the same tab moves right')
        assert ui.selected_tab == third
        assert tuple(row.identity for row in await database.tab_list()) == originals
        # Moving past the outside edge is a no-op, not a wrap to the other end.
        await ui.press('ctrl+shift+k')
        assert app.tab_order.names == originals and ui.selected_tab == third
        assert editor.text == 'HJKL'


async def test_sidebar_keys_follow_actual_edges_after_a_pointer_move(workspace):
    async with workspace.app(size=(130, 42)) as ui:
        app, pilot = ui.textual
        app.saved_settings.set(SETTINGS.ui.vim_keys, True)
        channels = app.screen.query_one('#channels-sidebar', SideBar)
        thread = app.selected_session.query_one('#thread-sidebar', SideBar)
        channels.reveal()
        thread.reveal()
        ui.conversation.prompt.focus()
        await ui.press('escape')
        assert ui.conversation.prompt.prompt_text_area.has_focus
        assert ui.conversation.prompt.prompt_text_area.editing_mode.allows_application_commands
        assert app.screen is app.workspace_screen
        await ui.step()
        await ui.press('ctrl+shift+h')
        assert channels.collapsed and not thread.collapsed
        await ui.press('ctrl+shift+h', 'ctrl+shift+l')
        assert not channels.collapsed and thread.collapsed
        await ui.press('ctrl+shift+l')
        assert not channels.collapsed and not thread.collapsed

        # Use the existing spatial control to move the right bar to the left.
        button = next(button for button in thread.query(SidebarAction)
                      if button.display and button.action.directional and button.action.direction == 'left')
        assert await pilot.click(button)
        await ui.step()
        assert not thread.right and not channels.right
        ui.conversation.prompt.focus()
        assert ui.conversation.prompt.prompt_text_area.editing_mode.allows_application_commands
        await ui.press('ctrl+shift+l')
        assert not channels.collapsed and not thread.collapsed
        await ui.press('ctrl+shift+h')
        assert channels.collapsed and thread.collapsed
        await ui.press('ctrl+shift+h')
        assert not channels.collapsed and not thread.collapsed
        channels.toggle(focus=False)
        await ui.step()
        assert channels.collapsed and not thread.collapsed
        await ui.press('ctrl+shift+h')
        assert channels.collapsed and thread.collapsed
        await ui.press('ctrl+shift+h')
        assert not channels.collapsed and not thread.collapsed


async def test_workspace_keys_do_not_interrupt_editor_sequences(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        app.saved_settings.set(SETTINGS.ui.vim_keys, True)
        await ui.new_session()
        selected = ui.selected_tab
        editor = ui.conversation.prompt.prompt_text_area
        await ui.press(*'abcHdef')
        await ui.press('escape', '0', 'f', 'H')
        assert editor.cursor_location == (0, 3)
        assert ui.selected_tab == selected and editor.has_focus
        await ui.press('2', 'H')
        assert ui.selected_tab == selected and editor.has_focus
        await ui.press('v', 'H')
        assert ui.selected_tab == selected and editor.has_focus
        await ui.press('escape', 'd', 'H')
        assert ui.selected_tab == selected and editor.has_focus
        assert editor.text == 'abcHdef'
