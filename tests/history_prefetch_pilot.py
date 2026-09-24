"""Earlier pages start loading before the viewport reaches its top edge."""

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms import MessageRoute, TranscriptCursor, TranscriptEvent, TranscriptPage, TurnRouting
from runtime_fixture import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-history-prefetch-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            file = "prefetch-fixture"
            tail = tuple(TranscriptEvent("assistant", f"Record {i}\n\n" + "Long line\n" * 5)
                         for i in range(64))
            calls = []

            async def loader(**kwargs):
                calls.append((view.window.scroll_y, kwargs))
                return TranscriptPage((TranscriptEvent("assistant", "OLDER_PREFETCHED_RECORD"),),
                                      TranscriptCursor(file, 0), TranscriptCursor(file, 100),
                                      False, True)

            history = TranscriptHistory(TranscriptPage(
                tail, TranscriptCursor(file, 100), TranscriptCursor(file, 200), True, False),
                loader=loader)
            await view.contents.mount(history)
            view.window.anchor()
            await pilot.pause()
            assert view.window.max_scroll_y > history._prefetch_distance + 4
            assert not calls, "Long tail fetched old content while still at latest"
            view.window.release_anchor()
            try:
                async with asyncio.timeout(8):
                    while not calls:
                        view.window.scroll_to(y=history._prefetch_distance - 1,
                                              animate=False, immediate=True)
                        await pilot.pause(.02)
            except TimeoutError:
                raise AssertionError({"scroll": view.window.scroll_y,
                                      "max_scroll": view.window.max_scroll_y,
                                      "prefetch": history._prefetch_distance,
                                      "region": history.region,
                                      "viewport": view.window.content_region,
                                      "older": history.has_older,
                                      "count": history.fragment_count,
                                      "limit": history.fragment_limit}) from None
            assert calls[0][0] > 2, "Older history was only fetched at the top"
            assert calls[0][1]["before"].offset == 100
            await pilot.pause()
            await history.remove()

            view.in_out_only = False
            filtered_calls = []
            route = TurnRouting(reply=MessageRoute("owner", ("#team",)))
            filtered_tail = (
                *(TranscriptEvent("thinking", f"HIDDEN_{index}") for index in range(90)),
                TranscriptEvent("sent", "VISIBLE_ROUTE\n\n" + "Long routed line\n\n" * 50,
                                routing=route),
            )

            async def filtered_loader(**kwargs):
                filtered_calls.append(view.window.scroll_y)
                return TranscriptPage((TranscriptEvent("sent", "FILTERED_PREFETCH", routing=route),),
                                      TranscriptCursor(file, 0), TranscriptCursor(file, 100),
                                      False, True)

            filtered = TranscriptHistory(TranscriptPage(
                filtered_tail, TranscriptCursor(file, 100), TranscriptCursor(file, 200),
                True, False), loader=filtered_loader)
            await view.contents.mount(filtered)
            view.window.anchor()
            await pilot.pause()
            assert view.window.max_scroll_y >= filtered._prefetch_distance + 4, (
                view.window.max_scroll_y, filtered._prefetch_distance,
                filtered.fragment_count, filtered.widget_count,
                filtered.pages[-1].start, filtered.pages[-1].stop,
                filtered._filter_before, filtered_calls)
            view.in_out_only = True
            await pilot.pause()
            assert not filtered_calls
            view.window.release_anchor()
            try:
                async with asyncio.timeout(8):
                    while not filtered_calls:
                        view.window.scroll_to(y=filtered._prefetch_distance - 1,
                                              animate=False, immediate=True)
                        await pilot.pause(.02)
            except TimeoutError:
                raise AssertionError(("Filtered prefetch never requested an older page",
                                      filtered._filter_before, view.window.scroll_y)) from None
            assert filtered_calls[0] > 2, "Filtered result was only fetched at the top"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("history prefetch: normal and filtered older pages start before the top edge")


if __name__ == "__main__":
    asyncio.run(main())
