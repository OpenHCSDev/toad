"""Sparse saved pages fill the viewport without evicting/reloading its tail."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from runtime_fixture import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-sparse-history-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        calls = []

        def page(index):
            return TranscriptPage(
                (TranscriptEvent("assistant", f"Saved activity {index}"),),
                TranscriptCursor("test", index), TranscriptCursor("test", index + 1),
                index > 0, index < 29,
            )

        async def load(*, before=None, after=None, through=None):
            index = before.offset - 1 if before is not None else after.offset
            calls.append(index)
            return page(index)

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            history = TranscriptHistory(page(29), load)
            await conversation.post(history)
            # Posting schedules a mount. Wait for the first page request before
            # deciding whether viewport filling has become idle.
            async with asyncio.timeout(5):
                while not history.is_mounted or not calls:
                    await pilot.pause(.05)
                previous_count = -1
                stable_ticks = 0
                while stable_ticks < 4:
                    await pilot.pause(.05)
                    count = len(calls)
                    at_older_edge = (history.has_older and
                                     history.region.y >= history.window.content_region.y - 2)
                    stable_ticks = (stable_ticks + 1 if count == previous_count and
                                    not history._loading and not at_older_edge else 0)
                    previous_count = count
            count = len(calls)
            await pilot.pause(1)
            assert len(calls) == count, (calls, count)
            assert len(calls) == len(set(calls)), calls
            assert not history.has_newer
            assert history.pages[-1].page.after.offset == 30
            assert conversation.window.follows_tail
            assert conversation.window.scroll_y == conversation.window.max_scroll_y
    print("sparse history: stable idle viewport, no repeated pages, latest retained")


if __name__ == "__main__":
    asyncio.run(main())
