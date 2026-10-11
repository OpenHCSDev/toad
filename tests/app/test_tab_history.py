"""Back and Forward step through visited tabs, whatever opened or closed them in between."""

BACK, FORWARD = "<──", "──>"


async def test_back_and_forward_walk_the_visited_tabs_and_keep_each_draft(workspace):
    workspace.thread("owner")
    async with workspace.app(size=(100, 36)) as ui:
        first = ui.selected_tab
        await ui.write_draft("Preserve first draft")
        assert not ui.can_go_back() and not ui.can_go_forward()
        await ui.click(BACK)
        assert ui.selected_tab == first

        channel = await ui.open_channel("#all", actor="owner")
        assert ui.selected_tab == channel
        assert ui.can_go_back() and not ui.can_go_forward()
        await ui.click(BACK)
        await ui.until(lambda: ui.selected_tab == first, why="Back to the first tab")
        await ui.click(FORWARD)
        await ui.until(lambda: ui.selected_tab == channel, why="Forward to the channel")

        second = await ui.new_session()
        await ui.write_draft("Preserve second draft")
        await ui.click(BACK)
        await ui.until(lambda: ui.selected_tab == channel, why="Back to the channel")
        await ui.click(BACK)
        await ui.until(lambda: ui.selected_tab == first, why="Back to the first tab")
        assert ui.draft() == "Preserve first draft"
        await ui.click(FORWARD)
        await ui.until(lambda: ui.selected_tab == channel, why="Forward to the channel")
        await ui.click(FORWARD)
        await ui.until(lambda: ui.selected_tab == second, why="Forward to the second session")
        assert ui.draft() == "Preserve second draft"


async def test_selecting_a_tab_after_back_branches_history_without_closing_tabs(workspace):
    workspace.thread("owner")
    async with workspace.app(size=(100, 36)) as ui:
        first = ui.selected_tab
        channel = await ui.open_channel("#all", actor="owner")
        second = await ui.new_session()
        await ui.click(BACK)
        await ui.until(lambda: ui.selected_tab == channel, why="Back to the channel")
        await ui.select_tab(first)
        assert ui.selected_tab == first
        assert not ui.can_go_forward()
        assert {tab.identity for tab in ui.tabs()} == {first, channel, second}


async def test_a_file_preview_tab_is_part_of_the_history_and_closing_it_returns_to_the_previous_tab(workspace):
    workspace.thread("owner")
    async with workspace.app(size=(100, 36)) as ui:
        first = ui.selected_tab
        await ui.write_draft("Preserve first draft")
        channel = await ui.open_channel("#all", actor="owner")
        second = await ui.new_session()
        await ui.select_tab(first)

        path = workspace.project / "readme.md"
        path.write_text("# Preview stays navigable\n")
        preview = await ui.open_preview(path)
        assert ui.selected_tab == preview
        await ui.click(BACK)
        await ui.until(lambda: ui.selected_tab == first, why="Back from the preview")
        await ui.click(FORWARD)
        await ui.until(lambda: ui.selected_tab == preview, why="Forward to the preview")
        await ui.close_tab(preview)
        assert ui.selected_tab == first
        await ui.close_tab(channel)
        assert {tab.identity for tab in ui.tabs()} == {first, second}
        assert ui.draft() == "Preserve first draft"


async def test_back_advances_even_when_closing_a_tab_leaves_two_visits_to_the_same_tab(workspace):
    async with workspace.app(size=(100, 36)) as ui:
        first = ui.selected_tab
        await ui.new_session()
        await ui.select_tab(first)
        path = workspace.project / "transient.txt"
        path.write_text("A removable history visit\n")
        transient = await ui.open_preview(path)
        await ui.select_tab(first)
        await ui.close_tab(transient)
        assert ui.can_go_back()

        await ui.click(BACK)
        await ui.until(ui.can_go_forward, why="the Back click to move the history cursor")
        assert ui.selected_tab == first
        await ui.click(BACK)
        await ui.until(lambda: ui.selected_tab != first, why="Back to reach another tab")
