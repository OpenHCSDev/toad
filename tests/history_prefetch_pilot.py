"""Earlier pages start loading before the viewport reaches its top edge."""

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript, SentTranscript, ThinkingTranscript
from runtime_fixture import ToadApp
from toad.widgets.message_filter import ALL_CATEGORIES, IN_OUT_CATEGORIES
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
            tail = tuple(AssistantTranscript(f'Record {i}\n\n' + 'Long line\n' * 5)
                         for i in range(64))
            calls = []

            async def loader(**kwargs):
                calls.append((view.window.scroll_y, kwargs))
                return TranscriptPage((AssistantTranscript('OLDER_PREFETCHED_RECORD'),),
                                      TranscriptCursor(file, 0), TranscriptCursor(file, 100),
                                      False, True)

            history = TranscriptHistory(TranscriptPage(
                tail, TranscriptCursor(file, 100), TranscriptCursor(file, 200), True, False),
                loader=loader)
            await view.contents.mount(history)
            view.window.anchor()
            await pilot.pause()
            assert view.window.max_scroll_y > history._prefetch_distance
            assert history.pages[0].page.before.offset == 100, "Lookahead mounted old content at the tail"
            view.window.release_anchor()
            try:
                async with asyncio.timeout(8):
                    while history.pages[0].page.before.offset != 0:
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
            assert view.window.scroll_y > 2, "Older history was only admitted at the top"
            assert calls[0][1]["before"].offset == 100
            assert len(calls) == 1, "Foreground admission repeated the prepared page read"
            await pilot.pause()
            await history.remove()

            view.visible_categories = ALL_CATEGORIES
            filtered_calls = []
            route = TurnRouting(reply=MessageRoute("owner", ("#team",)))
            filtered_tail = (
                *(ThinkingTranscript(f'HIDDEN_{index}') for index in range(90)),
                SentTranscript('VISIBLE_ROUTE\n\n' + 'Long routed line\n\n' * 50, routing=route),
            )

            async def filtered_loader(**kwargs):
                filtered_calls.append(view.window.scroll_y)
                return TranscriptPage((SentTranscript('FILTERED_PREFETCH', routing=route),),
                                      TranscriptCursor(file, 0), TranscriptCursor(file, 100),
                                      False, True)

            filtered = TranscriptHistory(TranscriptPage(
                filtered_tail, TranscriptCursor(file, 100), TranscriptCursor(file, 200),
                True, False), loader=filtered_loader)
            await view.contents.mount(filtered)
            view.window.anchor()
            await pilot.pause()
            assert view.window.max_scroll_y > filtered._prefetch_distance, (
                view.window.max_scroll_y, filtered._prefetch_distance,
                filtered.fragment_count, filtered.widget_count,
                filtered.pages[-1].start, filtered.pages[-1].stop,
                filtered.filter.before, filtered_calls)
            view.visible_categories = IN_OUT_CATEGORIES
            await pilot.pause()
            assert filtered.filter.overlay is None, "Lookahead published filtered rows at the tail"
            view.window.release_anchor()
            try:
                async with asyncio.timeout(8):
                    while filtered.filter.overlay is None:
                        view.window.scroll_to(y=filtered._prefetch_distance - 1,
                                              animate=False, immediate=True)
                        await pilot.pause(.02)
            except TimeoutError:
                raise AssertionError(("Filtered prefetch never requested an older page",
                                      filtered.filter.before, view.window.scroll_y)) from None
            assert view.window.scroll_y > 2, "Filtered result was only admitted at the top"
            assert len(filtered_calls) == 1
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("history prefetch: normal and filtered older pages start before the top edge")


if __name__ == "__main__":
    asyncio.run(main())
