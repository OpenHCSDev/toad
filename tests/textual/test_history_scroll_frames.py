"""Textual-facing: paging earlier history through the window keeps the reader's row on every painted frame, one load draws the rows missing ahead of the reader however few rows a message takes, and a channel keeps loading while its participants line waits for the sidebar.

Covers the transcript history and the channel history, which the same line history draws. Not carried over from the old script: nothing was dropped except that the transcript marker is now a
fragment's row (history is line-drawn) rather than the first message widget.
"""

import asyncio
import threading
from unittest.mock import patch

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage

from support.textual_steps import refresh_chat
from toad.transcript_preparation import PreparedTranscriptPage
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.history_anchor import HistoryAnchor
from toad.widgets.transcript_history import LineHistory, TranscriptHistory
from toad.wire_history import WireSource


def record_frames(app, row_of_marker):
    """Record `row_of_marker()` for every published frame until the returned function is called."""
    frames = []
    display = app._display

    def record(screen, renderable):
        if renderable is not None and not app._batch_count:
            row = row_of_marker()
            if row is not None:
                frames.append(row)
        return display(screen, renderable)

    app._display = record
    return frames, lambda: setattr(app, "_display", display)


async def test_transcript_paging_keeps_the_reader_row_on_every_frame_even_with_input_during_the_read(workspace):
    cursor = TranscriptCursor("fixture", 1)
    page = TranscriptPage(tuple(
        AssistantTranscript(f"Record {i}\n\n" + "\n".join(f"- item {j}" for j in range(20))) for i in range(30)),
        cursor, cursor, False, False)
    async with workspace.app(size=(110, 38)) as ui:
        app, _pilot = ui.textual
        conversation = ui.conversation
        history = await conversation.post(TranscriptHistory(page))
        await ui.until(lambda: history.is_mounted, why="the history mounted")
        window = conversation.window
        for cycle in range(3):
            positioning = history.reserve_source_work()
            window.scroll_to(y=1, animate=False, immediate=True)
            await ui.step()
            view = history.pages[0]
            fragment = view.fragments_in_range[0]

            def marker_row():
                offset = HistoryAnchor._placed_offset(view, window)
                line = view.fragment_line(fragment)
                return None if offset is None or line is None else offset + line - window.scroll_y

            expected = marker_row()
            frames, stop = record_frames(app, marker_row)
            history.finish_source_work(positioning)
            entered, release = asyncio.Event(), asyncio.Event()
            original = PreparedTranscriptPage.extend

            async def delayed_extend(prepared, *args, **kwargs):
                entered.set()
                await release.wait()
                return await original(prepared, *args, **kwargs)

            with patch.object(PreparedTranscriptPage, "extend", delayed_extend):
                history._request_page(True)
                async with asyncio.timeout(10):
                    await entered.wait()
                    if cycle == 1:
                        # Input arriving during the read must neither be undone nor cancel compensation.
                        window.scroll_relative(y=-1, animate=False, immediate=True)
                        await ui.step()
                        expected += 1
                        frames.clear()
                    release.set()
                await ui.until(lambda: history.state.accepts_source_work, why="the page admitted")
            await ui.step()
            stop()
            assert frames and set(frames) == {expected}, (expected, frames)
            assert not window.follows_tail


async def long_channel(workspace, ui):
    app, _pilot = ui.textual
    await ui.open_channel("#scroll", actor="sender")
    chat = app.screen.query_one(CommsChatView)
    history = chat.message_history
    await ui.until(lambda: history.messages and history.state.accepts_source_work, why="channel messages")
    return chat, history, chat.window


def scroll_messages(workspace):
    workspace.thread("sender", "scroll", running=True)
    for index in range(140):
        workspace.comms.messaging.send("sender", "#scroll", f"Message {index}: " + "wrapped body " * 30)


async def test_channel_paging_keeps_the_reader_row_on_every_frame(workspace):
    scroll_messages(workspace)
    async with workspace.app(size=(110, 38)) as ui:
        app, _pilot = ui.textual
        _chat, history, window = await long_channel(workspace, ui)
        for _ in range(3):
            await ui.until(lambda: history.state.accepts_source_work, why="the history idle")
            positioning = history.reserve_source_work()
            window.scroll_to(y=1, animate=False, immediate=True)
            await ui.step()
            view = history.pages[0]
            fragment = view.fragments_in_range[0]
            oldest = fragment.message.seq

            def marker_row():
                offset = HistoryAnchor._placed_offset(view, window)
                line = view.fragment_line(fragment)
                return None if offset is None or line is None else offset + line - window.scroll_y

            expected = marker_row()
            frames, stop = record_frames(app, marker_row)
            history.finish_source_work(positioning)
            history._request_page(True)
            await ui.until(lambda: history.messages[0].seq < oldest and history.state.accepts_source_work,
                           why="an earlier page drawn above")
            await ui.step()
            stop()
            assert frames and set(frames) == {expected}, (expected, frames)
            assert not window.follows_tail


def count_earlier_loads():
    """Count every load of earlier history any line history makes, until the patch is left."""
    loads = []
    load = LineHistory._load_page

    async def counted(history, older, *args, **kwargs):
        if older:
            loads.append(history)
        return await load(history, older, *args, **kwargs)

    return loads, patch.object(LineHistory, "_load_page", counted)


async def settled(ui, history, window):
    """Wait until the history has drawn the rows it keeps ahead of the reader, and return those above the screen."""
    def above():
        return window.region.y - history.region.y

    await ui.until(lambda: history.state.accepts_source_work
                   and (above() > history.prefetch_distance or not history.has_older),
                   seconds=20, why="the rows kept above the reader drawn")
    return above()


async def paged_back_twice(ui, history, window, loads):
    """Jump two screens up and report the loads it took to draw the rows above the reader again."""
    await settled(ui, history, window)
    assert history.has_older, "the history must still have earlier messages to load"
    before = len(loads)
    window.scroll_relative(y=-2 * window.outer_size.height, animate=False, immediate=True)
    await ui.step()
    await ui.until(lambda: window.lookahead.travel_rows == 0, why="the scroll no longer counted as travel")
    await settled(ui, history, window)
    return len(loads) - before


async def test_two_screens_back_in_a_channel_of_short_messages_are_refilled_by_a_few_loads(workspace):
    workspace.thread("sender", "scroll", running=True)
    for index in range(400):
        workspace.comms.messaging.send("sender", "#scroll", f"short {index}")
    loads, counting = count_earlier_loads()
    with counting:
        async with workspace.app(size=(110, 38)) as ui:
            _chat, history, window = await long_channel(workspace, ui)
            # A short message draws few rows: four of them are far less than a screen.
            taken = await paged_back_twice(ui, history, window, loads)
            assert taken <= 3, f"{taken} loads to draw two screens of short messages"


async def test_a_channel_loads_earlier_messages_while_its_participants_line_waits_for_the_sidebar(workspace):
    from toad.conversation_kind import ChannelConversation

    workspace.thread("sender", "scroll", running=True)
    for index in range(200):
        workspace.comms.messaging.send("sender", "#scroll", f"short {index}")
    waiting, release = asyncio.Event(), asyncio.Event()

    async def roster_waits(cls, view, comms):
        waiting.set()
        await release.wait()

    async with workspace.app(size=(110, 38)) as ui:
        chat, history, window = await long_channel(workspace, ui)
        await settled(ui, history, window)
        with patch.object(ChannelConversation, "update_roster", classmethod(roster_waits)):
            # A message arrives: the refresh draws nothing for a reader up here, then reads the participants.
            window.scroll_relative(y=-window.outer_size.height, animate=False, immediate=True)
            await ui.step()
            workspace.comms.messaging.send("sender", "#scroll", "ARRIVED")
            refresh = asyncio.create_task(refresh_chat(chat))
            await asyncio.wait_for(waiting.wait(), 10)
            window.scroll_relative(y=-2 * window.outer_size.height, animate=False, immediate=True)
            await ui.step()
            above = await settled(ui, history, window)
            assert not release.is_set() and above > history.prefetch_distance
            release.set()
            await refresh


async def test_two_screens_back_in_a_thread_of_short_records_are_refilled_by_a_few_loads(workspace):
    cursor = TranscriptCursor("fixture", 1)
    page = TranscriptPage(tuple(AssistantTranscript(f"short {i}") for i in range(400)), cursor, cursor, False, False)
    loads, counting = count_earlier_loads()
    with counting:
        async with workspace.app(size=(110, 38)) as ui:
            conversation = ui.conversation
            history = await conversation.post(TranscriptHistory(page))
            await ui.until(lambda: history.is_mounted, why="the history mounted")
            taken = await paged_back_twice(ui, history, conversation.window, loads)
            assert taken <= 3, f"{taken} loads to draw two screens of short records"


async def test_a_slow_channel_refresh_does_not_resume_follow_after_the_reader_scrolls(workspace):
    scroll_messages(workspace)
    async with workspace.app(size=(110, 38)) as ui:
        chat, history, window = await long_channel(workspace, ui)
        window.scroll_end(animate=False, immediate=True)
        await ui.step()
        entered, release = threading.Event(), threading.Event()
        real_read = WireSource.read

        def slow_read(source, request, through):
            if request.after is not None:
                entered.set()
                assert release.wait(10), "the held read was not released"
            return real_read(source, request, through)

        with patch.object(WireSource, "read", slow_read):
            workspace.comms.messaging.send("sender", "#scroll", "ARRIVED-DURING-SCROLL")
            refresh = asyncio.create_task(refresh_chat(chat))
            assert await asyncio.to_thread(entered.wait, 10)
            window.scroll_relative(y=-4, animate=False, immediate=True)
            await ui.step()
            seen = history.visible_fragments()[0]
            release.set()
            await refresh
            await ui.until(lambda: history.state.accepts_source_work and (history.has_newer or any(
                message.body == "ARRIVED-DURING-SCROLL" for message in history.messages)),
                why="the read to end with the new message below the reader")
        await ui.step()
        # The reader left the tail during the read: their place holds (whatever was drawn above it
        # meanwhile) and the new message waits below.
        assert not window.follows_tail and history.visible_fragments()[0] is seen
        assert not ui.shows("ARRIVED-DURING-SCROLL")
