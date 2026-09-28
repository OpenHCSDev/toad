"""Bounded background channel reads retain admission and never own read markers."""

import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
from threading import Event, get_ident
import unittest
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
from toad.conversation_kind import ChannelConversation, DmConversation
from toad.channel_preparation import (
    ChannelHistoryReader, HistoryReadRequest,
)


class ReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_dm_turn_lease_preserves_display_identity(self) -> None:
        import os

        with tempfile.TemporaryDirectory(prefix="dm-turn-basis-") as directory:
            root = Path(directory)
            comms = wire(root / "wire")
            comms.threads.register(Thread("peer", frozenset(), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
            viewer = comms.messaging.user_identity(str(root)).name
            comms.messaging.send("peer", viewer, "painted across turn claim")
            page = comms.views.dm_display_page("peer", worktree=str(root))
            identity = DmConversation.display_identity(page)
            comms.registry.lease_local_turn("peer", "new-turn")
            fresh = comms.views.dm_display_page("peer", worktree=str(root))
            self.assertEqual(identity, DmConversation.display_identity(fresh))

    async def test_any_mode_expansion_reloads_older_history_without_new_bus_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-scope-reader-") as directory:
            root = Path(directory)
            comms = wire(root / "wire")
            comms.threads.register(Thread("alice", frozenset({"team"}), str(root)))
            comms.threads.register(Thread("carol", frozenset({"team"}), str(root)))
            comms.threads.register(Thread("dave", frozenset(), str(root)))
            comms.messaging.send("carol", "dave", "older DM")
            comms.messaging.send("alice", "#team", "channel message")
            request = HistoryReadRequest(
                comms, ChannelConversation, "#team", root,
                False, 0, True, None, 8, 40, 256 * 1024,
            )
            first = request.read()
            assert first.page is not None
            self.assertEqual([m.body for m in first.page.messages], ["channel message"])
            assert first.page.display_scope is not None
            next_request = replace(
                request, initialized=True, after=first.high_water,
                known_revision=first.revision,
                known_display=request.kind.display_identity(first.page),
            )
            comms.channels.set_channel_any_mode("#team", True)
            self.assertEqual(comms.bus.log.latest_sequence(), first.high_water)
            expanded = next_request.read()
            self.assertTrue(expanded.replace_tail)
            assert expanded.page is not None
            self.assertEqual(
                [m.body for m in expanded.page.messages],
                ["older DM", "channel message"],
            )

    async def test_history_attachment_refreshes_without_new_live_messages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="history-attachment-") as directory:
            root = Path(directory)
            old = wire(root / "old")
            comms = wire(root / "live")
            for source in (old, comms):
                source.threads.register(Thread("alice", frozenset({"team"}), str(root)))
                source.messaging.send("alice", "#team", source.root.name)
            request = HistoryReadRequest(comms, ChannelConversation, "#team", root,
                False, 0, True, None, 8, 40, 256 * 1024)
            initial = request.read()
            request = replace(request, initialized=True, after=initial.high_water,
                known_revision=initial.revision, known_display=request.kind.display_identity(initial.page))
            comms.views.attach_history(old.root)
            refreshed = request.read()
            self.assertEqual(refreshed.high_water, initial.high_water)
            self.assertTrue(refreshed.replace_tail)
            self.assertTrue(refreshed.page.has_older)
            # Detaching changes the same inclusion basis without a new live sequence.
            detached_request = replace(request, known_revision=refreshed.revision,
                known_display=request.kind.display_identity(refreshed.page))
            comms.bus.history_manifest.unlink()
            detached = detached_request.read()
            self.assertTrue(detached.replace_tail)
            self.assertFalse(detached.page.has_older)

    async def test_revision_reuse_limits_and_cancelled_read_ownership(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-reader-") as directory:
            root = Path(directory)
            comms = wire(root)
            comms.threads.register(Thread("sender", frozenset({"one", "two"}), str(root)))
            for index in range(50):
                comms.messaging.send("sender", "#one", f"Message {index}")
            comms.messaging.user_identity(str(root))
            request = HistoryReadRequest(comms, ChannelConversation, "#one", root,
                                         False, 0, True, None, 8, 40, 256 * 1024)
            reader = ChannelHistoryReader()
            release = Event()
            try:
                with patch.object(comms.views, 'channel_display_page', wraps=comms.views.channel_display_page) as page:
                    result = await reader.read(request)
                    assert result.page is not None
                    self.assertLessEqual(len(result.page.messages), 8)
                    self.assertTrue(result.page.has_older)
                    reused = await reader.read(replace(request, initialized=True, after=result.high_water,
                                                       known_revision=result.revision))
                    self.assertIsNone(reused.page)
                    self.assertEqual(page.call_count, 1)

                # A cancelled UI waiter does not release an in-flight kernel read.
                entered = Event()
                original = comms.views.channel_display_page
                main_thread = get_ident()

                def gated(target, **kwargs):
                    self.assertNotEqual(get_ident(), main_thread)
                    if target == "#one":
                        entered.set()
                        if not release.wait(5):
                            raise TimeoutError("Test did not release channel read")
                    return original(target, **kwargs)

                with patch.object(comms.views, 'channel_display_page', side_effect=gated) as page:
                    first = asyncio.create_task(reader.read(request))
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    first.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await first
                    self.assertTrue(reader._pending)
                    # Cancellation does not cancel the actual I/O; a different
                    # current-view request can still complete independently.
                    active = await asyncio.wait_for(reader.read(replace(request, target="#two")), 2)
                    self.assertEqual(active.request.target, "#two")
                    release.set()
            finally:
                release.set()
                await reader.aclose()
            self.assertFalse(reader._pending)


if __name__ == "__main__":
    unittest.main(verbosity=2)
