"""Textual-facing: Ctrl+V pastes the application clipboard text when the clipboard holds no image."""

from unittest.mock import patch


async def test_ctrl_v_without_a_clipboard_image_pastes_the_clipboard_text(workspace):
    async with workspace.app() as ui:
        app, _pilot = ui.textual

        async def no_image():
            return None

        app.copy_to_clipboard("first\nsecond")
        with patch("toad.clipboard_image.read_clipboard_png", no_image):
            await ui.write_draft("")
            await ui.press("ctrl+v")
            await ui.until(lambda: ui.draft() == "first\nsecond", why="the clipboard text in the draft")
