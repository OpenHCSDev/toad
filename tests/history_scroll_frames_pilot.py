"""Paging must preserve the reader's position on every painted frame."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.transcript_history import TranscriptHistory, TranscriptPageView
from runtime_fixture import refresh_comms


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
            page = TranscriptPage(tuple(AssistantTranscript(f'Record {i}\n\n' + '\n'.join((f'- item {j}' for j in range(20)))) for i in range(30)),
                cursor, cursor, False, False)
            conversation = app.selected_session.conversation
            history = await conversation.post(TranscriptHistory(page))
            await pilot.pause()
            window = conversation.window
            for cycle in range(3):
                positioning = history.reserve_source_work()
                window.scroll_to(y=1, animate=False, immediate=True)
                await pilot.pause()
                marker = history.pages[0].fragment_views[0]
                expected = marker.region.y - window.content_region.y
                frames = []
                app.observed = marker, window, frames
                history.finish_source_work(positioning)
                entered, release = asyncio.Event(), asyncio.Event()
                original = TranscriptPageView.extend

                async def delayed_extend(view, older, current):
                    entered.set()
                    await release.wait()
                    await original(view, older, current)

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
                        while (not history.state.accepts_source_work):
                            await pilot.pause(.02)
                await pilot.pause()
                app.observed = None
                assert frames and set(frames) == {expected}, (expected, frames)
                assert not window.follows_tail

            comms = wire(root / "wire")
            comms.registry.declare(Thread("sender", frozenset({"scroll"}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
            for index in range(140):
                comms.messaging.send("sender", "#scroll", f"Message {index}: " + "wrapped body " * 30)
            await channel_target("#scroll").open(NavigationContext(app, app.selected_mode, root, "sender"))
            await pilot.pause()
            chat = app.screen.query_one(CommsChatView)
            window = chat.window
            for _ in range(3):
                operation = chat.message_history.reserve_source_work()
                window.scroll_to(y=1, animate=False, immediate=True)
                await pilot.pause()
                marker = chat.message_history.rows[0][1]
                expected = marker.region.y - window.content_region.y
                frames = []
                app.observed = marker, window, frames
                await operation.execute(chat.message_history, lambda: chat.message_history._load_page(True))
                await pilot.pause()
                app.observed = None
                assert frames and set(frames) == {expected}, (expected, frames)
            assert chat.message_history.has_newer, "Fixture must exercise eviction as well as prepending"

            # A slow refresh must not re-enable follow after the reader scrolls.
            window.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            entered, release = asyncio.Event(), asyncio.Event()
            original_refresh = chat.message_history.publish

            async def delayed_refresh(comms):
                follow = await original_refresh(comms)
                entered.set()
                await release.wait()
                return follow

            chat.message_history.reader.restart()
            with patch.object(chat.message_history, "publish", delayed_refresh):
                refresh = asyncio.create_task(refresh_comms(chat))
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
