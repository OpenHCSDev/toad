"""Textual-facing: Ctrl+V pastes the application clipboard text when the clipboard holds no image."""



async def test_ctrl_v_without_a_clipboard_image_pastes_the_clipboard_text(workspace, monkeypatch):
    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        app.copy_to_clipboard("first\nsecond")
        await ui.write_draft("")
        await ui.press("ctrl+v")
        await ui.until(lambda: ui.draft() == "first\nsecond", why="the clipboard text in the draft")
