"""Right and Left expand and collapse the channel whose header line has focus."""

from support.textual_steps import channel_roster


async def test_right_and_left_expand_and_collapse_a_channel_header(workspace):
    workspace.thread('keys-peer', 'keys')
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        tree = await channel_roster(ui, '#keys')
        group = tree.groups['#keys']
        row = group.row
        row.scroll_visible(animate=False)
        row.focus()
        await ui.until(lambda: app.focused is row, why='focus on the channel header line')

        await ui.press('left')
        await ui.until(lambda: not group.expanded, why='Left collapses the channel')
        assert row.render().plain.startswith('▸')
        await ui.press('left')
        assert not group.expanded, 'Left on a collapsed channel leaves it collapsed'

        await ui.press('right')
        await ui.until(lambda: group.expanded, why='Right expands the channel')
        assert row.render().plain.startswith('▾')
        await ui.press('right')
        assert group.expanded, 'Right on an expanded channel leaves it expanded'
        assert app.focused is row, 'expanding and collapsing keep focus on the header line'
