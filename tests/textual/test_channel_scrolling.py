"""Textual-facing: a long channel scrolls like a thread's history: held paging never draws a blank message area, the history grows under a reader without moving them, and End reaches the newest message with the draft untouched."""

from support.textual_steps import refresh_chat
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.presentation_window import NEWER_END


def messages(history):
    return tuple(fragment.message for fragment in history.fragments_in_range)


async def long_channel(workspace, ui):
    app, _pilot = ui.textual
    await ui.open_channel("#scroll", actor="sender")
    chat = app.screen.query_one(CommsChatView)
    history = chat.message_history
    await ui.until(lambda: messages(history) and history.state.accepts_source_work, why="channel messages")
    return chat, history, chat.window


def scroll_messages(workspace, count=260):
    workspace.thread("sender", "scroll", running=True)
    for index in range(count):
        workspace.comms.messaging.send("sender", "#scroll", f"Message {index}: " + "wrapped body " * 12)


async def test_plain_page_keys_scroll_a_quarter_page(workspace):
    scroll_messages(workspace, 40)
    async with workspace.app(size=(110, 35)) as ui:
        chat, history, window = await long_channel(workspace, ui)
        await ui.until(lambda: window.max_scroll_y > window.scrollable_content_region.height * 2,
                       why="scrollable conversation history")
        window.scroll_to(y=window.max_scroll_y / 2, animate=False, immediate=True)
        editor = chat.prompt.prompt_text_area
        editor.insert("Retained draft\nwith the cursor on its second line")
        editor.focus(scroll_visible=False)
        await ui.step()
        cursor, text = editor.cursor_location, editor.text
        before = window.scroll_y
        distance = max(1, window.scrollable_content_region.height // 4)
        await ui.press("pageup")
        await ui.until(lambda: window.scroll_y == before - distance,
                       why="PageUp to move a quarter page")
        assert editor.has_focus and editor.cursor_location == cursor and editor.text == text
        await ui.press("pagedown")
        await ui.until(lambda: window.scroll_y == before,
                       why="PageDown to move back a quarter page")
        assert editor.has_focus and editor.cursor_location == cursor and editor.text == text


def record_blank_frames(app, window):
    """Record, for every published frame, whether the message area drew any text."""
    frames = []
    display = app._display

    def record(screen, renderable):
        if renderable is not None and not app._batch_count and screen is app.screen:
            region = window.scrollable_content_region
            text = "".join("".join(strip.crop(region.x, region.right).text.split())
                           for strip in screen._compositor.render_strips()[region.y:region.bottom])
            frames.append(bool(text))
        return display(screen, renderable)

    app._display = record
    return frames, lambda: setattr(app, "_display", display)


async def test_held_paging_and_reversal_never_draw_a_blank_message_area_and_end_reaches_the_newest(workspace):
    scroll_messages(workspace)
    async with workspace.app(size=(110, 35)) as ui:
        app, _pilot = ui.textual
        chat, history, window = await long_channel(workspace, ui)
        editor = chat.prompt.prompt_text_area
        editor.insert("retained channel draft")
        editor.history.checkpoint()
        editor.insert(" with undo")
        document, edit_history = editor.document, editor.history
        newest = messages(history)[-1].seq
        frames, stop = record_blank_frames(app, window)
        try:
            window.focus(scroll_visible=False)
            # Held PageUp far past the first pages, PageDown, and a reversal part of the way.
            for key, presses in (("pageup", 40), ("pagedown", 12), ("pageup", 12)):
                for _ in range(presses):
                    await ui.press(key)
            await ui.until(lambda: history.state.accepts_source_work, why="paging to settle")
            assert messages(history)[0].seq < newest - 100, "paging up did not reach earlier pages"
            assert not window.follows_tail
            await ui.press("end")
            await ui.until(lambda: window.follows_tail and window.scroll_y == window.max_scroll_y
                           and messages(history) and messages(history)[-1].seq == newest and not history.has_more(NEWER_END),
                           why="End to reach the newest message")
        finally:
            stop()
        assert frames and all(frames), f"{frames.count(False)} of {len(frames)} frames had an empty message area"
        await ui.until_shows("Message 259:")
        assert editor.document is document and editor.history is edit_history
        editor.undo()
        assert editor.text == "retained channel draft"


async def test_a_growing_channel_draws_new_messages_for_a_tail_reader_and_keeps_a_scrolled_reader_in_place(workspace):
    scroll_messages(workspace, 80)
    comms = workspace.comms
    async with workspace.app(size=(110, 35)) as ui:
        chat, history, window = await long_channel(workspace, ui)
        await ui.until_shows("Message 79:")
        comms.messaging.send("sender", "#scroll", "GROWN-AT-TAIL")
        await refresh_chat(chat)
        await ui.until_shows("GROWN-AT-TAIL")
        assert window.follows_tail

        window.focus(scroll_visible=False)
        for _ in range(8):
            await ui.press("pageup")
        await ui.until(lambda: history.state.accepts_source_work and not window.follows_tail, why="the reader above the tail")
        await ui.step()
        def message_rows():
            # Read the message area, excluding sidebar and scrollbar ink.
            region = window.scrollable_content_region
            rows = (strip.crop(region.x, region.right).text
                    for strip in ui.app.screen._compositor.render_strips()[region.y:region.bottom])
            return [line for line in rows if "Message" in line]

        position, top = window.scroll_y, message_rows()
        for index in range(60):
            comms.messaging.send("sender", "#scroll", f"GROWN-WHILE-AWAY {index}")
        await refresh_chat(chat)
        await ui.until(lambda: history.state.accepts_source_work and history.has_more(NEWER_END), why="the new messages offered")
        await ui.step()
        # The reader's rows did not move and nothing new was drawn over them.
        assert window.scroll_y == position and not window.follows_tail
        assert not ui.shows("GROWN-WHILE-AWAY")
        assert top and message_rows() == top
        await ui.press("end")
        await ui.until(lambda: window.follows_tail and not history.has_more(NEWER_END), why="End to reach the newest message")
        await ui.until_shows("GROWN-WHILE-AWAY 59")
