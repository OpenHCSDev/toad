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
