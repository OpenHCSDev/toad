"""Thread and channel tabs keep one opening order whichever tab is selected."""


async def test_interleaved_tabs_keep_opening_order_through_selection_and_close(workspace):
    workspace.thread("owner")
    async with workspace.app(size=(140, 32)) as ui:
        first = ui.selected_tab
        channel = await ui.open_channel("#all", actor="owner")
        second = await ui.new_session()
        expected = [first, channel, second]
        for identity in expected * 2:
            await ui.select_tab(identity)
            assert [tab.identity for tab in ui.tabs()] == expected
            assert ui.selected_tab == identity
        await ui.close_tab(channel)
        expected.remove(channel)
        for identity in expected:
            await ui.select_tab(identity)
            assert [tab.identity for tab in ui.tabs()] == expected
