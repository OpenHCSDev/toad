"""Textual-facing: the prompt's text area keeps focus, cursor, document and undo history while tabs
are parked, selected and clicked; typing, arrows, backspace, delete and undo edit one document."""

from toad.widgets.session_tabs import SessionLabel


async def edit_keys(ui, area):
    """Typing and deletion exercise the same native editor document and undo."""
    initial, cursor = area.text, area.cursor_location
    assert area.has_focus
    area.history.checkpoint()
    await ui.press(*"abcd", "left")
    assert area.cursor_location == (cursor[0], cursor[1] + 3)
    await ui.press("backspace", "delete")
    assert area.text == initial[:cursor[1]] + "ab" + initial[cursor[1]:]
    await ui.press("left", "right")
    assert area.cursor_location == (cursor[0], cursor[1] + 2)
    await ui.press("backspace", "backspace")
    assert area.text == initial and area.cursor_location == cursor
    area.history.checkpoint()
    await ui.press("ctrl+z")
    assert area.text != initial
    await ui.press("backspace", "backspace")
    assert area.text == initial


async def test_editor_keys_work_after_clicks_parking_and_returning_between_tabs(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        first = app.selected_session
        first_area = first.conversation.prompt.prompt_text_area
        assert await pilot.click(first_area)
        await edit_keys(ui, first_area)
        # The logical source releases its native focus before parking.
        # Hide must not select an unrelated intermediate frame target.
        await app.workspace_sessions.retire()
        assert app.workspace_screen.focused is None
        assert not first.display
        await ui.select_tab(first.id)
        await ui.until(lambda: first_area.has_focus, why="the editor focused on return")
        await ui.press("escape", "tab", "shift+tab")
        assert await pilot.click(first_area)
        await edit_keys(ui, first_area)
        await app.session_navigation.create_from(first.id)
        await ui.step()
        second = app.selected_session
        for source in (first, second, first):
            tab = app.screen.query_one(f"SessionLabel#{source.id}", SessionLabel)
            assert await pilot.click(tab)
            await ui.until(lambda: app.selected_session is source, why="the clicked tab selected")
            area = source.conversation.prompt.prompt_text_area
            await ui.until(lambda: area.has_focus, why="the editor focused after the tab click")
            await edit_keys(ui, area)
        assert first_area.document is first.conversation.prompt.prompt_text_area.document
        assert ui.failure() is None
