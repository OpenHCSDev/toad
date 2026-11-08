"""Textual-facing: a long channel scrolls like a thread's history: held paging never draws a blank message area, the history grows under a reader without moving them, and End reaches the newest message with the draft untouched."""

from support.textual_steps import painted_text, refresh_chat
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.presentation_window import NEWER_END, OLDER_END
from toad.widgets.transcript_history import LineHistory


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
        # Earlier pages load above the reader while it moves, and restoration
        # keeps the content where it was: travel is measured on the content.
        fragment = history.visible_fragments()[0]

        def row():
            return history.fragment_shown(fragment).top(-1)

        before = row()
        distance = max(1, window.scrollable_content_region.height // 4)
        await ui.press("pageup")
        await ui.until(lambda: row() == before + distance,
                       why="PageUp to move a quarter page")
        assert editor.has_focus and editor.cursor_location == cursor and editor.text == text
        await ui.press("pagedown")
        await ui.until(lambda: row() == before,
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
        oldest_loaded = messages(history)[0].seq
        frames, stop = record_blank_frames(app, window)
        try:
            window.focus(scroll_visible=False)
            # Held PageUp until the window needs an older page than it opened with. A quarter
            # page per press (#1256) can travel a long way inside what is already loaded, so a
            # fixed count asked for a load the reader never needed. The travel left bounds it.
            while messages(history)[0].seq >= oldest_loaded and (
                    window.scroll_y > 0 or history.has_more(OLDER_END)):
                before = window.scroll_y, messages(history)[0].seq
                await ui.press("pageup")
                assert (window.scroll_y, messages(history)[0].seq) != before, "PageUp stopped moving"
            # PageDown, then a reversal part of the way.
            for key, presses in (("pagedown", 12), ("pageup", 12)):
                for _ in range(presses):
                    await ui.press(key)
            await ui.until(lambda: history.state.accepts_source_work, why="paging to settle")
            # Plain PageUp moves a quarter page (#1256); held, it must still load
            # pages older than the ones the channel opened with.
            assert messages(history)[0].seq < oldest_loaded, "paging up did not reach earlier pages"
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


async def test_paging_down_at_the_bottom_keeps_the_reader_on_the_tail(workspace):
    """A page down at the bottom released the anchor and moved nothing, so no scroll change
    told the window the reader was still at the end: "Back to bottom" showed at the bottom."""
    scroll_messages(workspace, 80)
    async with workspace.app(size=(110, 35)) as ui:
        chat, history, window = await long_channel(workspace, ui)
        await ui.until_shows("Message 79:")
        await ui.until(lambda: window.follows_tail, why="the reader on the tail")
        window.focus(scroll_visible=False)
        for _ in range(2):
            window.action_page_down()
            await ui.step()
        await ui.until(lambda: window.follows_tail and not window.jump_bar.display,
                       why="the reader at the bottom to keep following")


async def test_a_reader_left_at_the_end_by_a_geometry_change_follows_the_tail(workspace):
    """Being at the end is geometry: a reader released at the bottom whom a layout leaves there
    (a tool collapsing below them, a resize) follows again with no scroll of their own."""
    scroll_messages(workspace, 80)
    async with workspace.app(size=(110, 35)) as ui:
        chat, history, window = await long_channel(workspace, ui)
        await ui.until_shows("Message 79:")
        await ui.until(lambda: window.follows_tail, why="the reader on the tail")
        window.release_anchor()
        assert not window.follows_tail and window.scroll_y >= window.max_scroll_y
        await ui.resize(110, 42)  # taller: the end moves up to meet the reader, who is clamped there
        await ui.until(lambda: window.follows_tail and not window.jump_bar.display,
                       why="the reader the layout left at the end to follow")


async def test_scrolling_prepared_history_keeps_its_intrinsic_content_geometry(workspace, monkeypatch):
    """A reader moves prepared rows; those rows do not acquire new layouts."""
    scroll_messages(workspace, 40)
    async with workspace.app(size=(70, 28)) as ui:
        chat, history, window = await long_channel(workspace, ui)
        for _ in range(4):
            await ui.press("pageup")
        await ui.until(lambda: window.max_scroll_y > 12,
                       why="prepared rows on both sides of the scroll trial")
        window.scroll_to(y=window.max_scroll_y / 2, animate=False, immediate=True)
        await ui.step()
        screen = ui.app.screen
        captured = screen._compositor._subtree_geometry[history]
        calls = []
        arrange = LineHistory.arrange

        def arranged(document, *args, **kwargs):
            calls.append(document)
            return arrange(document, *args, **kwargs)

        monkeypatch.setattr(LineHistory, "arrange", arranged)
        initial = window.scroll_y
        for delta in (-3, -3, 3, 3):
            window.scroll_to(y=window.scroll_y + delta, animate=False, immediate=True)
            await ui.step()
        assert window.scroll_y == initial
        assert not calls, "scrolling rediscovered unchanged prepared history layout"
        assert screen._compositor._subtree_geometry[history] is captured
        assert history.visible_fragments(), "the reused source still draws its prepared messages"


async def test_the_placement_scan_answers_once_per_publication(workspace):
    """The sticky header asks which page is under the top row on every scroll tick.

    Where a page sits is layout-space and which pages are drawn come from the published
    frame, so the answer changes when the publication does and not when scroll_y does.
    Rebuilding it per tick cost 1.005s of a 31s phone trace inside top_message_header,
    allocating an ancestor chain per page and walking the layout map for each one.

    The reuse is only worth having if the header still names the right sender, so this
    asserts what the header paints, from two senders whose headers differ. An earlier
    version of this test compared top_message_header() with top_page().pinned_header(),
    which is its own one-line body: a stale answer agrees with itself.
    """
    workspace.thread("alpha", "scroll", running=True)
    workspace.thread("beta", "scroll", running=True)
    for index in range(16):
        workspace.comms.messaging.send("alpha", "#scroll", f"Alpha {index}: " + "wrapped body " * 12)
    for index in range(16):
        workspace.comms.messaging.send("beta", "#scroll", f"Beta {index}: " + "wrapped body " * 12)

    async with workspace.app(size=(110, 35)) as ui:
        app, _pilot = ui.textual
        await ui.open_channel("#scroll", actor="alpha")
        chat = app.screen.query_one(CommsChatView)
        window = chat.window
        await ui.until(lambda: window.max_scroll_y > window.scrollable_content_region.height,
                       why="scrollable conversation history")

        builds = 0
        original = type(window).placed_in

        def counted(self, geometry, widgets):
            nonlocal builds
            builds += 1
            return original(self, geometry, widgets)

        # The newest messages are beta's, so the tail pins beta's header.
        window.scroll_to(y=window.max_scroll_y, animate=False, immediate=True)
        await ui.step()
        await ui.until(lambda: painted_text(window.sticky_header, "beta"),
                       why="the pinned header names the sender at the top row")

        type(window).placed_in = counted
        try:
            # Asking again inside one publication must not scan again, and the painted
            # header must still be beta's rather than blank or alpha's.
            for _ in range(8):
                window.placed_pages()
                window.top_message_header()
            assert builds <= 1, "an unchanged publication is answered without scanning again"
            assert painted_text(window.sticky_header, "beta"), "the held answer still paints beta"

            # Real scrolling back through alpha's messages must repaint alpha's header.
            scanned = builds
            window.scroll_to(y=0, animate=False, immediate=True)
            await ui.step()
            await ui.until(lambda: not window.sticky_header.display
                                   or painted_text(window.sticky_header, "alpha"),
                           why="the pinned header follows the reader back to alpha")
            assert builds > scanned, "a republished frame scans again"

            # A real width publication is a new answer the header must follow.
            window.scroll_to(y=window.max_scroll_y, animate=False, immediate=True)
            await ui.step()
            republished = builds
            await ui.resize(90, 30)
            await ui.step()
            assert builds > republished, "the resized publication scans again"
            # The header is pinned only while a message's own header is scrolled above the
            # top row, so the tail of a republished frame may legitimately pin nothing.
            # Re-establish a known position rather than guess the new geometry.
            window.scroll_to(y=window.max_scroll_y, animate=False, immediate=True)
            window.scroll_relative(y=-2, animate=False, immediate=True)
            await ui.step()
            await ui.until(lambda: painted_text(window.sticky_header, "beta"),
                           why="the republished frame still pins beta inside beta's message")
        finally:
            type(window).placed_in = original
