"""Paging must preserve the reader's position on every painted frame."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import Thread, TranscriptCursor, TranscriptEvent, TranscriptPage, wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.transcript_history import TranscriptHistory, TranscriptPageView


class ScrollFrameApp(ToadApp):
    observed = None

    def _display(self, screen, renderable):
        if self.observed is not None and renderable is not None and not self._batch_count:
            widget, window, frames = self.observed
            if widget.is_attached:
                frames.append(widget.region.y - window.content_region.y)
        return super()._display(screen, renderable)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-scroll-frames-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ScrollFrameApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause()
            cursor = TranscriptCursor("fixture", 1)
            page = TranscriptPage(tuple(TranscriptEvent("assistant", f"Record {i}\n\n" +
                "\n".join(f"- item {j}" for j in range(20))) for i in range(30)),
                cursor, cursor, False, False)
            conversation = app.screen.conversation
            history = await conversation.post(TranscriptHistory(page))
            await pilot.pause()
            window = conversation.window
            for cycle in range(3):
                history._loading = True
                window.scroll_to(y=1, animate=False, immediate=True)
                await pilot.pause()
                marker = history.pages[0].children[0]
                expected = marker.region.y - window.content_region.y
                frames = []
                app.observed = marker, window, frames
                history._loading = False
                entered, release = asyncio.Event(), asyncio.Event()
                original = TranscriptPageView.extend

                async def delayed_extend(view, older):
                    entered.set()
                    await release.wait()
                    await original(view, older)

                with patch.object(TranscriptPageView, "extend", delayed_extend):
                    history._request_page(True)
                    async with asyncio.timeout(10):
                        await entered.wait()
                        if cycle == 1:
                            # Input arriving during mount must neither be undone
                            # nor cancel compensation for the incoming records.
                            window.scroll_relative(y=-1, animate=False, immediate=True)
                            await pilot.pause()
                            expected += 1
                            frames.clear()
                        release.set()
                        while history._loading:
                            await pilot.pause(.02)
                await pilot.pause()
                app.observed = None
                assert frames and set(frames) == {expected}, (expected, frames)
                assert not window.follows_tail

            comms = wire(root / "wire")
            comms.register(Thread("sender", frozenset({"scroll"}), str(root), pid=os.getpid()))
            for index in range(140):
                comms.send("sender", "#scroll", f"Message {index}: " + "wrapped body " * 30)
            await app.open_comms_session(owner_mode=app.current_mode, project_path=root,
                                         me="sender", target="#scroll", kind="channel")
            await pilot.pause()
            chat = app.screen.query_one(CommsChatView)
            window = chat.window
            for _ in range(3):
                chat._edge_load_scheduled = True
                window.scroll_to(y=1, animate=False, immediate=True)
                await pilot.pause()
                marker = chat._history[0][1]
                expected = marker.region.y - window.content_region.y
                frames = []
                app.observed = marker, window, frames
                await chat._load_history_edge()
                await pilot.pause()
                app.observed = None
                assert frames and set(frames) == {expected}, (expected, frames)
            assert chat._has_newer, "Fixture must exercise eviction as well as prepending"

            # A slow refresh must not re-enable follow after the reader scrolls.
            window.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            entered, release = asyncio.Event(), asyncio.Event()
            original_refresh = chat._refresh_history

            async def delayed_refresh(comms):
                follow = await original_refresh(comms)
                entered.set()
                await release.wait()
                return follow

            chat._revision = None
            with patch.object(chat, "_refresh_history", delayed_refresh):
                refresh = asyncio.create_task(chat._refresh())
                async with asyncio.timeout(10):
                    await entered.wait()
                    window.scroll_relative(y=-4, animate=False, immediate=True)
                    await pilot.pause()
                    expected = window.scroll_y
                    release.set()
                    await refresh
                await pilot.pause()
                assert not window.follows_tail and window.scroll_y == expected
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("history scroll: transcript/IRC prepend and eviction stable on every frame; concurrent input preserved")


if __name__ == "__main__":
    asyncio.run(main())
