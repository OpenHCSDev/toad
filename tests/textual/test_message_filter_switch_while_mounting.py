"""Textual-facing: while a filtered history projection is being prepared or mounted, Textual keeps typing and tab clicks live and the history widget drops the stale projection."""

import asyncio
import threading
from unittest.mock import patch

from agent_comms.messages import Message, MessageType
from agent_comms.routing import MessageRoute
from agent_comms.transcript_events import (
    AssistantTranscript, IncomingTranscript, ThinkingTranscript,
)
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual.await_complete import AwaitComplete
from textual.containers import VerticalGroup

from toad.transcript_preparation import TranscriptFilterWork
from toad.widgets.message_filter import InboundCategory, ThinkingCategory, all_categories
from toad.widgets.transcript_history import TranscriptHistory

import pytest


def incoming(text):
    message = Message("peer", "owner", text, MessageType.INFO, timestamp=0)
    return IncomingTranscript(message.body, route=MessageRoute(message.sender, (message.target,)),
                              source=message.reference)


def texts(history):
    return [fragment.events[0].text for fragment in history.fragments_in_range]


@pytest.mark.parametrize("stage", ["prepare", "container"])
async def test_filter_change_during_mount_retires_the_old_projection(workspace, stage):
    async with workspace.app(size=(120, 40)) as ui:
        app, _ = ui.textual
        view = ui.conversation
        view.visible_categories = all_categories()
        events = (incoming("OLD_INBOUND"), ThinkingTranscript("NEW_THINKING")) * 8 + tuple(
            AssistantTranscript(f"tail {i}") for i in range(4))
        pager = TranscriptHistory(TranscriptPage(
            events, TranscriptCursor("mount-fixture", 0), TranscriptCursor("mount-fixture", len(events)),
            False, False))
        entered, release = asyncio.Event(), asyncio.Event()
        original_mount = VerticalGroup.mount
        original_submit = app.preparation.submit
        held = False

        async def submitted(work):
            nonlocal held
            result = await original_submit(work)
            if stage == "prepare" and isinstance(work, TranscriptFilterWork) and not held:
                held = True
                entered.set()
                await release.wait()
            return result

        def mounted(parent, *widgets, **kwargs):
            nonlocal held
            result = original_mount(parent, *widgets, **kwargs)
            if stage == "container" and parent is pager and not held:
                held = True

                async def wait():
                    await result
                    entered.set()
                    await release.wait()

                return AwaitComplete(wait())
            return result

        with patch.object(pager, "request_preparation"), patch.object(TranscriptHistory, "_check_edges"):
            await view.contents.mount(pager)
            await ui.step()
            view.visible_categories = frozenset((InboundCategory,))
            scan = None
            try:
                with patch.object(VerticalGroup, "mount", mounted), patch.object(app.preparation, "submit", submitted):
                    scan = asyncio.create_task(pager.filter.scan_older())
                    await asyncio.wait_for(entered.wait(), 5)
                    view.visible_categories = frozenset((ThinkingCategory,))
                    view.prompt.focus()
                    await ui.press("x")
                    assert view.prompt.text.endswith("x"), "Typing blocked behind filter mount"
                    assert app._batch_count == 0, "A held page batch suppressed unrelated presentation"
                    owner_tab = ui.selected_tab
                    await ui.new_session()
                    other_view = ui.conversation
                    assert other_view.visible_categories == all_categories()
                    other_view.prompt.focus()
                    await ui.press("y")
                    assert other_view.prompt.text == "y", "Another thread froze behind the old filter"
                    position = [tab.identity for tab in ui.tabs()].index(owner_tab)
                    await ui.click(ui.tabs()[position].title, occurrence=0)
                    assert ui.selected_tab == owner_tab
                    assert view.visible_categories == frozenset((ThinkingCategory,))
                    release.set()
                    await asyncio.wait_for(scan, 5)
                    assert pager.filter.before is None, "Stale filter advanced the new filter cursor"
                await ui.step()
                await pager.filter.scan_older()
                await ui.step()
                assert pager.filter.overlay is not None
                assert all(text == "NEW_THINKING" for text in texts(pager.filter.overlay))
            finally:
                release.set()
                if scan is not None:
                    await asyncio.gather(scan, return_exceptions=True)
                await pager.remove()


async def test_filtered_history_arrives_in_small_batches_off_the_loop(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        view = ui.conversation
        view.visible_categories = all_categories()
        events = tuple(event for index in range(20) for event in (
            incoming(f"INBOUND_{index}"), ThinkingTranscript(f"THINKING_{index}"),
        )) + tuple(AssistantTranscript(f"tail {index}") for index in range(4))
        page = TranscriptPage(events, TranscriptCursor("batch-fixture", 0),
                              TranscriptCursor("batch-fixture", len(events)), False, False)
        pager = TranscriptHistory(page)
        threads = []
        prepare = TranscriptFilterWork.prepare

        def prepared(work):
            threads.append(threading.get_ident())
            return prepare(work)

        with patch.object(pager, "request_preparation"), patch.object(TranscriptHistory, "_check_edges"), \
                patch.object(TranscriptFilterWork, "prepare", prepared):
            await view.contents.mount(pager)
            await ui.step()
            view.visible_categories = frozenset((InboundCategory,))
            previous = 0
            while pager.filter.has_older:
                await pager.filter.scan_older()
                count = len(pager.filter.overlay.fragments_in_range)
                assert 0 < count - previous <= 4, "Source-sized widget admission"
                previous = count
                await ui.step()
            assert texts(pager.filter.overlay) == [f"INBOUND_{i}" for i in range(20)]
            assert pager.pages[0].page is page, "Filtering replaced canonical source data"
            assert threads and all(thread != threading.get_ident() for thread in threads)
            assert not pager.filter.overlay.has_older
            await pager.remove()


async def test_empty_filter_reads_no_history_and_a_later_selection_finds_the_match(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        view = ui.conversation
        view.visible_categories = frozenset()
        cursor = TranscriptCursor("empty-filter", 10)
        calls = []

        async def earlier(**kwargs):
            calls.append(kwargs)
            return TranscriptPage((incoming("SELECTED_INBOUND"),), TranscriptCursor("empty-filter", 0), cursor,
                                  False, True)

        pager = TranscriptHistory(TranscriptPage((ThinkingTranscript("TAIL"),),
                                                 cursor, TranscriptCursor("empty-filter", 20), True, False),
                                  loader=earlier)
        await view.contents.mount(pager)
        await ui.step()
        assert not calls, "Empty filter speculatively read history that cannot match"
        assert not pager.older.display and not pager.newer.display
        view.visible_categories = frozenset((InboundCategory,))
        await ui.until(lambda: pager.filter.overlay is not None and "SELECTED_INBOUND" in texts(pager.filter.overlay),
                       seconds=5, why="the selected inbound message in the filtered history")
        assert calls
