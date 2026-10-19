"""Textual-facing: messages drawn as rows sit on their view's background, and the block cursor rests on one of them: Alt+Up/Down move it message by message, its menu copies the message and (in a channel) opens the sender or destination, and hovering shows the message's full time."""

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import NativeTranscriptCursor, TranscriptPage
from support.roots import FIXTURE_SNAPSHOT

from toad.widgets.menu import Menu
from toad.widgets.message_divider import MessageClock
from toad.widgets.note import Note
from toad.widgets.transcript_history import TranscriptHistory


def style_at(ui, text, occurrence=0):
    return ui.textual[0].screen.get_style_at(*ui._cell_of(text, occurrence))


async def choose(ui, view, key):
    await ui.press("enter")
    await ui.until(lambda: bool(view.query(Menu)), why="the message's menu")
    await ui.press(key)
    await ui.until(lambda: not view.query(Menu), why="the menu to close")


async def test_channel_rows_have_the_view_background_and_the_cursor_acts_on_one_message(workspace):
    workspace.thread("owner", "team", running=True)
    workspace.thread("peer", "team", running=True)
    for word in ("first", "second", "third"):
        workspace.comms.messaging.send("peer", "#team", f"{word} words")
    wire_root = str(workspace.roots.wire)
    async with workspace.app(size=(100, 36)) as ui:
        app, pilot = ui.textual
        owner = ui.selected_tab
        app.selected_session.initial_coordination_root = wire_root
        app.selected_session._comms_thread = "owner"
        existing = await ui.new_session()
        app.selected_session.initial_coordination_root = wire_root
        app.selected_session._comms_thread = "peer"
        await ui.select_tab(owner)
        channel = await ui.open_channel("#team", actor="owner", owner=owner)
        await ui.until_shows("third words")
        view = ui.conversation
        history = view.message_history
        page = history.pages[-1]

        # Text, the blank row between messages and the header rule all sit on the page's background.
        background = page.rich_style.bgcolor
        assert background is not None
        column, row = ui._cell_of("third words", 0)
        for x, y in ((column, row), (column, row - 2), (column, row - 1), (90, row)):
            assert app.screen.get_style_at(x, y).bgcolor == background, (x, y)
        # A name leads somewhere and is drawn so; the notification line toggles and is not.
        await ui.until(lambda: style_at(ui, "peer → #team").underline, why="the sender underlined as a link")
        assert not style_at(ui, "▶ ", 0).underline

        # Alt+Up from the prompt lands on the newest message, then moves one message at a time.
        await ui.press("alt+up")
        if view.cursor_block is not history:
            # The channel's activity line below the messages is a block of its own.
            await ui.press("alt+up")
        cursor = view.navigation.cursor
        assert view.cursor_block is history
        assert cursor.fragment.message.body == "third words"
        region = cursor.visible_region
        assert region is not None and region.y <= row < region.bottom
        await ui.press("alt+up")
        assert cursor.fragment.message.body == "second words"
        await choose(ui, view, "c")
        assert app.clipboard == "peer → #team: second words"
        await ui.press("alt+down")
        assert cursor.fragment.message.body == "third words"
        await ui.press("alt+down")
        assert view.cursor_block is not history, "past the newest message the cursor leaves the history"

        # A click puts the cursor on the message clicked.
        await ui.click("first words")
        await ui.until(lambda: view.navigation.cursor is not None, why="the cursor on the clicked message")
        assert view.navigation.cursor.fragment.message.body == "first words"

        # Hovering shows that message's full time.
        assert await pilot.hover(offset=ui._cell_of("first words", 0))
        first = view.navigation.cursor.fragment.message
        assert first.timestamp is not None
        assert page.tooltip == MessageClock.recorded(first.timestamp).display()[1]
        assert await pilot.hover(offset=ui._cell_of("third words", 0))
        assert page.tooltip == MessageClock.recorded(history.messages[-1].timestamp).display()[1]

        # The menu opens the sender's thread: here its already open tab.
        await choose(ui, view, "s")
        await ui.until(lambda: ui.selected_tab == existing, seconds=3, why="the sender's tab")
        await ui.select_tab(channel)
        await ui.click("second words")
        await ui.until(lambda: view.navigation.cursor is not None, why="the cursor on the clicked message")
        assert [item.description for item in view.navigation.cursor.get_block_menu()] == [
            "Open [u]s[/u]ender", "Open [u]d[/u]estination"]
        assert ui.failure() is None


async def test_saved_thread_history_rows_have_the_view_background_and_the_cursor_copies_one_message(workspace):
    cursor = NativeTranscriptCursor("fixture", 1)
    page = TranscriptPage(tuple(AssistantTranscript(f"RECORD_{i} in *Markdown*") for i in range(6)),
                          cursor, cursor, False, False, FIXTURE_SNAPSHOT)
    async with workspace.app(size=(110, 38)) as ui:
        app, _pilot = ui.textual
        view = ui.conversation
        history = TranscriptHistory(page)
        await view.post(history)
        await view.contents.mount(Note("LIVE_NOTE"))
        await ui.until_shows("RECORD_5")
        drawn = history.pages[-1]
        background = drawn.rich_style.bgcolor
        assert background is not None
        column, row = ui._cell_of("RECORD_5", 0)
        for x, y in ((column, row), (column, row + 1), (100, row)):
            assert app.screen.get_style_at(x, y).bgcolor == background, (x, y)

        await ui.press("alt+up")
        await ui.press("alt+up")
        cursor = view.navigation.cursor
        assert view.cursor_block is history
        assert cursor.get_clipboard_text() == "RECORD_5 in *Markdown*"
        await ui.press("alt+up")
        assert cursor.get_clipboard_text() == "RECORD_4 in *Markdown*"
        await choose(ui, view, "c")
        assert app.clipboard == "RECORD_4 in *Markdown*"
        assert ui.failure() is None
