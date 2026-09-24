"""Filtered history must fill empty viewport from older routed records."""

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms import MessageRoute, TranscriptCursor, TranscriptEvent, TranscriptPage, TurnRouting
from runtime_fixture import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-in-out-underfill-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 44)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            conversation.in_out_only = True
            file = "read-only-fixture"
            tail = tuple(TranscriptEvent("thinking", f"HIDDEN_TAIL_{index}")
                         for index in range(90))
            older = TranscriptEvent("sent", "OLDER_ROUTED_MESSAGE",
                                    routing=TurnRouting(reply=MessageRoute("owner", ("#team",))))
            calls = []

            async def load_page(**kwargs):
                calls.append(kwargs)
                return TranscriptPage((older,), TranscriptCursor(file, 0),
                                      TranscriptCursor(file, 100), False, True)

            history = TranscriptHistory(TranscriptPage(
                tail, TranscriptCursor(file, 100), TranscriptCursor(file, 200), True, False),
                loader=load_page)
            await conversation.contents.mount(history)
            conversation.window.anchor()
            await pilot.pause()

            def routed_visible(pager):
                return (pager._filter_overlay is not None and
                        any(leaf.display and leaf.fragment.events[0].text == older.text
                            for leaf in pager._filter_overlay.children))

            try:
                async with asyncio.timeout(8):
                    while not routed_visible(history):
                        await pilot.pause(.02)
            except TimeoutError:
                raise AssertionError({"reads": len(calls), "raw_fragments": history.fragment_count,
                                      "limit": history.fragment_limit,
                                      "scroll": conversation.window.max_scroll_y,
                                      "older": history.has_older}) from None
            assert calls and len(calls) <= 3, "Underfill walked the same page indefinitely"
            assert conversation.in_out_only and conversation.window.max_scroll_y >= 0
            assert history.pages[-1].page.events == tail, (
                [len(page.page.events) for page in history.pages], history.pages[0].page.before,
                history._filter_before)
            assert history.widget_count < history.widget_limit
            await pilot.pause()
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "OLDER_ROUTED_MESSAGE" in frame, "The older result was mounted but not painted"
            await history.remove()

            # More hidden fragments than the raw widget budget must not make
            # a still-empty filtered viewport permanently unscrollable.
            longer_tail = tuple(TranscriptEvent("thinking", f"HIDDEN_OLDER_{index}")
                                for index in range(340))
            calls.clear()
            sparse = TranscriptHistory(TranscriptPage(
                longer_tail, TranscriptCursor(file, 100), TranscriptCursor(file, 200), True, False),
                loader=load_page)
            await conversation.contents.mount(sparse)
            conversation.window.anchor()
            try:
                async with asyncio.timeout(8):
                    while not routed_visible(sparse):
                        await pilot.pause(.02)
            except TimeoutError:
                raise AssertionError({"sparse_reads": len(calls),
                                      "raw_fragments": sparse.fragment_count,
                                      "mounted_widgets": sparse.widget_count,
                                      "scroll": conversation.window.max_scroll_y,
                                      "older": sparse.has_older}) from None
            assert len(calls) <= 3, "Sparse scan repeated a bounded page"
            assert sparse.widget_count < sparse.widget_limit, "Hidden fragments mounted to fill the view"
            assert sparse._filter_overlay is not None and sparse._filter_overlay.display
            await pilot.pause()
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "OLDER_ROUTED_MESSAGE" in frame, "Sparse older result was not painted"
            conversation.in_out_only = False
            await pilot.pause()
            assert not sparse._filter_overlay.display
            assert any(leaf.display for leaf in sparse.pages[-1].children), (
                "Unchecking did not restore retained native transcript")
            conversation.in_out_only = True
            await pilot.pause()
            assert sparse._filter_overlay.display, "Filtered older results vanished after retoggling"
            await sparse.remove()

            # Exhaust a finite history with no routed rows. The auto-loader
            # stops on the captured oldest cursor; it must not reread forever.
            empty_reads = []

            async def only_hidden(**kwargs):
                empty_reads.append(kwargs["before"].offset)
                offset = 50 if kwargs["before"].offset == 100 else 0
                return TranscriptPage((TranscriptEvent("thinking", "NO_ROUTE"),),
                                      TranscriptCursor(file, offset),
                                      TranscriptCursor(file, kwargs["before"].offset),
                                      bool(offset), True)

            empty = TranscriptHistory(TranscriptPage(
                tail, TranscriptCursor(file, 100), TranscriptCursor(file, 200), True, False),
                loader=only_hidden)
            await conversation.contents.mount(empty)
            conversation.window.anchor()
            async with asyncio.timeout(5):
                while empty._filter_before is None or empty._filter_has_older:
                    await pilot.pause(.02)
            assert empty_reads == [100, 50], empty_reads
            await pilot.pause(.2)
            assert empty_reads == [100, 50], "No-route history was scanned again"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("in/out underfill: older routed message appeared without resizing or unchecking")


if __name__ == "__main__":
    asyncio.run(main())
