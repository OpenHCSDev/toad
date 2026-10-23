"""Textual-facing: keys sent in one burst to the driver while the history window has focus reach the editor in order.

The window hands focus to the editor on a printable key; keys that arrive before that transfer completes
must not be lost, reordered or applied to the wrong control.
"""

from toad.agent_binding import NoAgentConnection

from textual import events


async def send_burst(ui, keys):
    app, _pilot = ui.textual
    editor = ui.conversation.prompt.prompt_text_area
    editor.clear()
    target = ui.conversation.window
    target.focus(scroll_visible=False)
    await ui.until(lambda: app.screen.focused is target, why="the burst's starting focus")
    for key, character in keys:
        event = events.Key(key, character)
        event.set_sender(app)
        app._driver.send_message(event)
    return editor


async def test_a_character_and_an_immediate_backspace_in_one_burst_leave_nothing(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        assert isinstance(ui.conversation.agent_binding, NoAgentConnection)
        editor = await send_burst(ui, (("x", "x"), ("backspace", None)))
        await ui.until(lambda: ui.shows("❯"), why="the editor drawn")
        await ui.step(.2)
        assert editor.text == "", "Printable insert succeeded but immediate deletion failed"
        assert ui.failure() is None


async def test_a_character_a_left_arrow_and_a_character_in_one_burst_keep_their_order(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        editor = await send_burst(ui, (("x", "x"), ("left", None), ("y", "y")))
        await ui.step(.2)
        assert editor.text == "yx", f"Native arrow/printable burst lost editor key ordering: {editor.text!r}"
        assert ui.failure() is None

