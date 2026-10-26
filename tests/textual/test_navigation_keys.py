"""Workspace navigation keys operate original tabs; editors retain typed capitals."""

from toad.preferences import SETTINGS
from toad.widgets.side_bar import SideBar, SidebarAction


async def test_history_tab_selection_and_persisted_reorder_keep_original_tabs(workspace):
    async with workspace.app(size=(130, 42)) as ui:
        app, pilot = ui.textual
        app.saved_settings.set(SETTINGS.ui.vim_keys, True)
        first = ui.selected_tab
        second = await ui.new_session()
        third = await ui.new_session()
        originals = app.tab_order.names

        async def navigate(key, expected):
            ui.conversation.window.focus()
            await ui.press(key)
            await ui.until(lambda: ui.selected_tab == expected, why=f'{key} selects its original tab')

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

        ui.conversation.window.focus()
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
        ui.conversation.window.focus()
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
        ui.conversation.window.focus()
        await ui.press('ctrl+shift+l')
        assert not channels.collapsed and not thread.collapsed
        await ui.press('ctrl+shift+h')
        assert channels.collapsed and thread.collapsed
        await ui.press('ctrl+shift+h')
        assert not channels.collapsed and not thread.collapsed
