"""Bounded background channel reads retain admission and never own read markers."""

import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
from threading import Event, get_ident
import unittest
from unittest.mock import patch

from agent_comms import Thread, wire
from toad.channel_preparation import (
    ChannelHistoryReader, HistoryKind, HistoryReadRequest, display_identity,
)


class ReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_bus_replacement_reloads_unchanged_sequence_tail(self) -> None:
        for kind, target in ((HistoryKind.CHANNEL, "#team"), (HistoryKind.DIRECT, "peer")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix="channel-rebind-") as directory:
                root = Path(directory)
                comms = wire(root / "wire")
                comms.register(Thread("peer", frozenset({"team"}), str(root)))
                viewer = comms.user_identity(str(root)).name
                comms.send("peer", viewer if kind is HistoryKind.DIRECT else target, "original")
                request = HistoryReadRequest(
                    comms, kind, target, root, False, 0, True, None, 8, 40, 256 * 1024,
                )
                first = request.read()
                assert first.page is not None
                following = replace(
                    request, initialized=True, after=first.high_water,
                    known_revision=first.revision,
                    known_display=display_identity(kind, first.page),
                )
                bus = comms.bus._path
                replacement = bus.with_suffix(".replacement")
                replacement.write_bytes(bus.read_bytes().replace(b"original", b"replaced"))
                replacement.replace(bus)
                refreshed = following.read()
                self.assertEqual(refreshed.high_water, first.high_water)
                self.assertTrue(refreshed.replace_tail)
                assert refreshed.page is not None
                self.assertEqual([message.body for message in refreshed.page.messages], ["replaced"])

    async def test_dm_turn_claim_preserves_display_identity(self) -> None:
        import os

        with tempfile.TemporaryDirectory(prefix="dm-turn-basis-") as directory:
            root = Path(directory)
            comms = wire(root / "wire")
            comms.register(Thread("peer", frozenset(), str(root), pid=os.getpid()))
            viewer = comms.user_identity(str(root)).name
            comms.send("peer", viewer, "painted across turn claim")
            page = comms.dm_display_page("peer", worktree=str(root))
            identity = display_identity(HistoryKind.DIRECT, page)
            comms.registry.claim_local_turn("peer", "new-turn")
            fresh = comms.dm_display_page("peer", worktree=str(root))
            self.assertEqual(identity, display_identity(HistoryKind.DIRECT, fresh))

    async def test_any_mode_expansion_reloads_older_history_without_new_bus_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-scope-reader-") as directory:
            root = Path(directory)
            comms = wire(root / "wire")
            comms.register(Thread("alice", frozenset({"team"}), str(root)))
            comms.register(Thread("carol", frozenset({"team"}), str(root)))
            comms.register(Thread("dave", frozenset(), str(root)))
            comms.send("carol", "dave", "older DM")
            comms.send("alice", "#team", "channel message")
            request = HistoryReadRequest(
                comms, HistoryKind.CHANNEL, "#team", root,
                False, 0, True, None, 8, 40, 256 * 1024,
            )
            first = request.read()
            assert first.page is not None
            self.assertEqual([m.body for m in first.page.messages], ["channel message"])
            assert first.page.display_scope is not None
            next_request = replace(
                request, initialized=True, after=first.high_water,
                known_revision=first.revision,
                known_display=display_identity(request.kind, first.page),
            )
            comms.set_channel_any_mode("#team", True)
            self.assertEqual(comms.message_high_water(), first.high_water)
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
                source.register(Thread("alice", frozenset({"team"}), str(root)))
                source.send("alice", "#team", source.root.name)
            request = HistoryReadRequest(comms, HistoryKind.CHANNEL, "#team", root,
                False, 0, True, None, 8, 40, 256 * 1024)
            initial = request.read()
            request = replace(request, initialized=True, after=initial.high_water,
                known_revision=initial.revision, known_display=display_identity(request.kind, initial.page))
            comms.attach_history(old.root)
            refreshed = request.read()
            self.assertEqual(refreshed.high_water, initial.high_water)
            self.assertTrue(refreshed.replace_tail)
            self.assertTrue(refreshed.page.has_older)
            # Detaching changes the same inclusion basis without a new live sequence.
            detached_request = replace(request, known_revision=refreshed.revision,
                known_display=display_identity(request.kind, refreshed.page))
            comms.bus.history_manifest.unlink()
            detached = detached_request.read()
            self.assertTrue(detached.replace_tail)
            self.assertFalse(detached.page.has_older)

    async def test_revision_reuse_limits_and_background_admission(self) -> None:
        with tempfile.TemporaryDirectory(prefix="channel-reader-") as directory:
            root = Path(directory)
            comms = wire(root)
            comms.register(Thread("sender", frozenset({"one", "two"}), str(root)))
            for index in range(50):
                comms.send("sender", "#one", f"Message {index}")
            comms.user_identity(str(root))
            request = HistoryReadRequest(comms, HistoryKind.CHANNEL, "#one", root,
                                         False, 0, True, None, 8, 40, 256 * 1024)
            reader = ChannelHistoryReader()
            release = Event()
            try:
                with patch.object(comms, "channel_display_page", wraps=comms.channel_display_page) as page:
                    result = await reader.read(request, background=True)
                    assert result.page is not None
                    self.assertLessEqual(len(result.page.messages), 8)
                    self.assertTrue(result.page.has_older)
                    reused = await reader.read(request, result, background=True)
                    self.assertIs(reused, result)
                    self.assertEqual(page.call_count, 1)

                # A cancelled UI waiter does not release an in-flight kernel read.
                entered = Event()
                original = comms.channel_display_page
                main_thread = get_ident()

                def gated(target, **kwargs):
                    self.assertNotEqual(get_ident(), main_thread)
                    if target == "#one":
                        entered.set()
                        if not release.wait(5):
                            raise TimeoutError("Test did not release channel read")
                    return original(target, **kwargs)

                with patch.object(comms, "channel_display_page", side_effect=gated) as page:
                    first = asyncio.create_task(reader.read(request, background=True))
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    first.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await first
                    queued = asyncio.create_task(reader.read(replace(request, target="#two"), background=True))
                    await asyncio.sleep(0)
                    self.assertEqual(page.call_count, 1)
                    # Foreground uses its own I/O slot rather than joining the
                    # queue for unrelated inactive tabs.
                    active = await asyncio.wait_for(reader.read(replace(request, target="#two")), 2)
                    self.assertEqual(active.request.target, "#two")
                    release.set()
                    await asyncio.wait_for(queued, 3)
            finally:
                release.set()
                await reader.aclose()
            self.assertFalse(reader._pending)


if __name__ == "__main__":
    unittest.main(verbosity=2)
