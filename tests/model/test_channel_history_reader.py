"""Bounded background channel reads reuse unchanged revisions, follow scope changes and join cancelled reads."""

import asyncio
from dataclasses import replace
from threading import Event, get_ident
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import wire
from agent_comms.threads import Thread

from toad.channel_preparation import ChannelHistoryReader, InitialHistoryReadRequest
from toad.conversation_kind import ChannelConversation, DmConversation


def test_a_turn_claim_on_the_peer_keeps_the_direct_message_page_identity(tmp_path):
    import os

    comms = wire(tmp_path / "wire")
    comms.registry.declare(Thread("peer", frozenset(), str(tmp_path), process_identity=ProcessIdentity.capture(os.getpid())))
    viewer = comms.messaging.user_identity(str(tmp_path)).name
    comms.messaging.send("peer", viewer, "shown across turn claim")
    identity = DmConversation.display_identity(comms.views.dm_display_page("peer", worktree=str(tmp_path)))
    comms.registry.lease_local_turn("peer", "new-turn")
    assert identity == DmConversation.display_identity(comms.views.dm_display_page("peer", worktree=str(tmp_path)))


def test_any_mode_expansion_reloads_older_history_without_new_bus_rows(tmp_path):
    comms = wire(tmp_path / "wire")
    comms.registry.declare(Thread("alice", frozenset({"team"}), str(tmp_path)))
    comms.registry.declare(Thread("carol", frozenset({"team"}), str(tmp_path)))
    comms.registry.declare(Thread("dave", frozenset(), str(tmp_path)))
    comms.messaging.send("carol", "dave", "older DM")
    comms.messaging.send("alice", "#team", "channel message")
    request = InitialHistoryReadRequest(comms, ChannelConversation, "#team", tmp_path, 8, 40, 256 * 1024)
    first = request.read()
    assert first.page is not None
    assert [m.body for m in first.page.messages] == ["channel message"]
    assert first.page.display_scope is not None
    next_request = request.advance(first, True)
    comms.channels.set_channel_any_mode("#team", True)
    assert comms.bus.log.latest_sequence() == first.high_water
    expanded = next_request.read()
    assert expanded.replace_tail
    assert expanded.page is not None
    assert [m.body for m in expanded.page.messages] == ["older DM", "channel message"]


def test_attaching_or_detaching_history_refreshes_without_new_live_messages(tmp_path):
    old = wire(tmp_path / "old")
    comms = wire(tmp_path / "live")
    for source in (old, comms):
        source.registry.declare(Thread("alice", frozenset({"team"}), str(tmp_path)))
        source.messaging.send("alice", "#team", source.root.name)
    request = InitialHistoryReadRequest(comms, ChannelConversation, "#team", tmp_path, 8, 40, 256 * 1024)
    initial = request.read()
    request = request.advance(initial, True)
    comms.views.attach_history(old.root)
    refreshed = request.read()
    assert refreshed.high_water == initial.high_water
    assert refreshed.replace_tail
    assert refreshed.page.has_older
    # Detaching changes the same inclusion basis without a new live sequence.
    detached_request = request.advance(refreshed, True)
    comms.bus.history.path.unlink()
    detached = detached_request.read()
    assert detached.replace_tail
    assert not detached.page.has_older


async def test_unchanged_revision_is_reused_and_a_cancelled_read_stays_joined_until_its_io_ends(tmp_path):
    comms = wire(tmp_path / "wire")
    comms.registry.declare(Thread("sender", frozenset({"one", "two"}), str(tmp_path)))
    for index in range(50):
        comms.messaging.send("sender", "#one", f"Message {index}")
    comms.messaging.user_identity(str(tmp_path))
    request = InitialHistoryReadRequest(comms, ChannelConversation, "#one", tmp_path, 8, 40, 256 * 1024)
    reader = ChannelHistoryReader(request)
    release = Event()
    try:
        with patch.object(comms.views, "channel_display_page", wraps=comms.views.channel_display_page) as page:
            result = await reader.read(True)
            assert result.page is not None
            assert len(result.page.messages) <= 8
            assert result.page.has_older
            reader.accept(result, True)
            reused = await reader.read(True)
            assert reused.page is None
            assert page.call_count == 1

        # A new message makes the ordinary incremental read necessary.
        comms.messaging.send("sender", "#one", "arrived before cancellation")
        # A cancelled UI waiter does not release an in-flight kernel read.
        entered = Event()
        original = comms.views.channel_display_page
        main_thread = get_ident()

        def gated(target, **kwargs):
            assert get_ident() != main_thread
            if target == "#one":
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release channel read")
            return original(target, **kwargs)

        with patch.object(comms.views, "channel_display_page", side_effect=gated):
            first = asyncio.create_task(reader.read(True))
            assert await asyncio.to_thread(entered.wait, 2)
            first.cancel()
            try:
                await first
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("the cancelled waiter returned a result")
            assert reader._pending
            # Cancellation does not cancel the actual I/O; a different
            # current-view request can still complete independently.
            other = ChannelHistoryReader(replace(request, target="#two"))
            try:
                active = await asyncio.wait_for(other.read(True), 2)
                assert active.request.target == "#two"
            finally:
                await other.aclose()
            release.set()
    finally:
        release.set()
        await reader.aclose()
    assert not reader._pending


async def test_rows_next_to_an_edge_come_from_transport_pages_that_are_read_once_and_can_be_read_ahead(tmp_path):
    comms = wire(tmp_path / "wire")
    comms.registry.declare(Thread("sender", frozenset({"one"}), str(tmp_path)))
    for index in range(100):
        comms.messaging.send("sender", "#one", f"Message {index}")
    comms.messaging.user_identity(str(tmp_path))
    reader = ChannelHistoryReader(InitialHistoryReadRequest(comms, ChannelConversation, "#one", tmp_path, 8, 40, 256 * 1024))
    try:
        with patch.object(comms.views, "channel_display_page", wraps=comms.views.channel_display_page) as core_read:
            tail = await reader.read(True)
            reader.accept(tail, True)
            assert [message.body for message in tail.page.messages] == [f"Message {index}" for index in range(92, 100)]
            reads, edge, bodies = core_read.call_count, tail.page.oldest_cursor, []

            # Ten admissions of four rows cost one Core read, not ten.
            for _ in range(10):
                part = await reader.page(before=edge, limit=4)
                assert len(part.messages) == 4 and part.has_older
                bodies[:0] = [message.body for message in part.messages]
                edge = part.oldest_cursor
            assert bodies == [f"Message {index}" for index in range(52, 92)]
            assert core_read.call_count == reads + 1

            # A request that is no longer current reads nothing.
            await reader.read_ahead(True, edge, 60, lambda: False)
            assert core_read.call_count == reads + 1
            # Reading ahead stops at the start of history: 52 older messages are two reads.
            await reader.read_ahead(True, edge, 60, lambda: True)
            assert core_read.call_count == reads + 3
            await reader.read_ahead(True, edge, 60, lambda: True)
            assert core_read.call_count == reads + 3

            # A new message at the tail leaves the older pages held.
            comms.messaging.send("sender", "#one", "arrived while scrolled up")
            reader.accept(await reader.read(False), False)
            reads = core_read.call_count
            while part.has_older:
                part = await reader.page(before=edge, limit=4)
                bodies[:0] = [message.body for message in part.messages]
                edge = part.oldest_cursor
            assert bodies == [f"Message {index}" for index in range(92)]
            assert core_read.call_count == reads

            # A restarted source reads again.
            reader.restart()
            again = await reader.page(before=tail.page.oldest_cursor, limit=4)
            assert [message.body for message in again.messages] == [f"Message {index}" for index in range(88, 92)]
            assert core_read.call_count == reads + 1
    finally:
        await reader.aclose()
