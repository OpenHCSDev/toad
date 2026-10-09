"""Retiring an editor preserves its document/history without retaining its UI."""

import pytest

from textual.app import App
from textual.widgets import TextArea
from textual.widgets.text_area import Selection


@pytest.mark.parametrize("language", [None, "python"])
async def test_editor_state_preserves_document_selection_and_undo_redo(language):
    app = App()
    async with app.run_test(size=(70, 18)) as pilot:
        first = TextArea("one\ntwo\n", language=language)
        await app.mount(first)
        await pilot.pause()
        first.insert("changed", location=(1, 3))
        first.selection = Selection((0, 1), (1, 4))
        state = first.capture_editor_state()
        text = first.text
        await first.remove()

        second = TextArea()
        await app.mount(second)
        second.restore_editor_state(state)
        await pilot.pause()
        assert second.document is state.document
        assert second.history is state.history
        assert second.text == text
        assert second.selection == state.selection
        assert second.language == language
        second.undo()
        assert second.text == "one\ntwo\n"
        second.redo()
        assert second.text == text
        assert first._closed and second.is_attached


async def test_editor_state_rewraps_at_destination_width_and_retains_scroll():
    app = App()
    async with app.run_test(size=(70, 15)) as pilot:
        first = TextArea("\n".join(f"line {i} " + "words " * 12 for i in range(60)))
        await app.mount(first)
        await pilot.pause()
        first.move_cursor((25, 3))
        first.scroll_to(y=20, animate=False, immediate=True)
        await pilot.pause()
        state = first.capture_editor_state()
        await first.remove()
        await pilot.resize_terminal(40, 15)
        second = TextArea()
        await app.mount(second)
        second.restore_editor_state(state)
        await pilot.pause()
        assert second.selection == state.selection
        assert second.scroll_y == state.scroll_y
        assert second.wrapped_document is not first.wrapped_document
        expected_text = second.text
        second.insert("!")
        second.undo()
        assert second.text == expected_text
