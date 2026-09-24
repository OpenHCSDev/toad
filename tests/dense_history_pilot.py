"""Rich history retention is bounded by real widget cost, not record count alone."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from runtime_fixture import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-dense-history-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        cursor = TranscriptCursor("fixture", 1)
        page = TranscriptPage(tuple(TranscriptEvent("assistant",
            f"Record {i}\n\n" + "\n".join(f"- item {j}" for j in range(20))) for i in range(30)),
            cursor, cursor, False, False)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            history = TranscriptHistory(page)
            await view.post(history)
            await pilot.pause()
            peak = history.widget_count
            for _ in range(10):
                before = history.pages[0].start
                view.window.scroll_home(animate=False, immediate=True)
                try:
                    async with asyncio.timeout(5):
                        while history.pages[0].start >= before or history._loading:
                            await pilot.pause(.02)
                except TimeoutError:
                    raise AssertionError((before, [(p.start, p.stop) for p in history.pages],
                        history._loading, history.widget_count, history.widget_limit,
                        history.window.scroll_y, history.window.max_scroll_y,
                        history.window.follows_tail, history.region)) from None
                peak = max(peak, history.widget_count)
                assert history.widget_count <= history.widget_limit
            print({"peak_history_widgets": peak, "widget_budget": history.widget_limit,
                   "retained_fragments": history.fragment_count})
            assert history.has_newer and history.has_older
        # Cancelling a UI worker does not stop its already-running to_thread
        # read. Drain those test-owned reads before deleting their wire files.
        await asyncio.get_running_loop().shutdown_default_executor()
    print("dense history: off-screen rich widget trees retired while both paging directions remain available")


if __name__ == "__main__":
    asyncio.run(main())
