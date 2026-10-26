"""Sorting opens at its label and writes through the existing ordering owners."""

import json

from agent_comms.comms import wire
from agent_comms.display_order import CreatedThreadSort
from support.textual_steps import channel_roster
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.session_sort import ChannelListSort


async def test_sort_dropdown_is_anchored_persists_and_dismisses(workspace):
    workspace.thread('sort-peer', 'sorting')
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        tree = await channel_roster(ui, '#sorting')
        control = tree.groups['#sorting'].sort_control
        control.scroll_visible(animate=False)
        control.focus()
        await ui.step()
        anchor = control.region
        before = control.order
        assert await pilot.click(control)
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why='the sort dropdown')
        menu = app.screen
        await ui.step()
        assert menu.options.region.x == anchor.x
        assert menu.options.region.y == anchor.bottom
        assert [str(menu.options.get_option_at_index(i).prompt) for i in range(3)] == [
            'Sent', 'Created', 'Active']
        await pilot.press('escape')
        await ui.until(lambda: app.screen is not menu, why='Escape dismissal')
        assert control.order is before
        assert control.has_focus

        await pilot.press('enter')
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why='keyboard-opened sort dropdown')
        menu = app.screen
        await pilot.press('home', 'down', 'enter')
        await ui.until(lambda: control.order is CreatedThreadSort, why='the observed saved order')
        assert wire(workspace.roots.wire).bus.require_channel('#sorting').order is CreatedThreadSort

        assert await pilot.click(control)
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why='dropdown before outside click')
        menu = app.screen
        await pilot.click(offset=(110, 38))
        await ui.until(lambda: app.screen is not menu, why='outside-click dismissal')
        assert control.order is CreatedThreadSort

        filters = app.workspace_chrome.channels.query_one(ChannelListSort)
        filters.scroll_visible(animate=False)
        await ui.step()
        previous = app.settings.sidebar.show_stopped
        assert await pilot.click(filters)
        await ui.until(lambda: isinstance(app.screen, ContextMenu), why='channel sort and filter dropdown')
        menu = app.screen
        option = next(i for i in range(menu.options.option_count)
                      if 'Show stopped' in str(menu.options.get_option_at_index(i).prompt))
        menu.options.highlighted = option
        await pilot.press('enter')
        await ui.until(lambda: app.settings.sidebar.show_stopped is not previous,
                       why='the visibility setting to change')
        path = workspace.roots.attempt / 'config' / 'toad' / 'toad.json'
        await ui.until(lambda: path.exists() and json.loads(path.read_text()).get('sidebar', {}).get('show_stopped') is not None,
                       why='the visibility preference to be saved')
        assert json.loads(path.read_text())['sidebar']['show_stopped'] is not previous
