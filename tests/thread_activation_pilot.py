"""Returning to a thread paints its intended viewport without replaying old scroll positions."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from toad.acp.messages import TranscriptSnapshot
from toad.app import ToadApp
from toad.screens.main import MainScreen
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation
from toad.widgets.transcript_history import TranscriptHistory


class FrameApp(ToadApp):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = None

    def _display(self, screen, renderable):
        if (self.frames is not None and renderable is not None
                and not self._batch_count and screen is self.screen):
            conversation = screen.query_one_optional(Conversation)
            if conversation is not None:
                window = conversation.window
                region = window.content_region
                text = "\n".join(
                    strip.text[region.x:region.right]
                    for strip in screen._compositor.render_strips()[region.y:region.bottom]
                )
                self.frames.append((self.current_mode, window.scroll_y, window.max_scroll_y, text))
        return super()._display(screen, renderable)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-thread-activation-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            conversation = app.screen.conversation
            response = await conversation.post(AgentResponse("\n\n".join(f"Old paragraph {i}" for i in range(40))))
            window = conversation.window
            window.anchor()
            await pilot.pause()
            other = await app.new_session_screen(lambda: MainScreen(root))
            # Grow and reflow a hidden live view, then return before any visible
            # transcript refresh has had a chance to repair its viewport.
            await response.append("\n\n" + "\n\n".join(f"New paragraph {i}" for i in range(400)) + "\n\nLATEST-ACTIVITY")
            await pilot.resize_terminal(75, 24)
            app.frames = []
            await app.switch_mode(owner)
            await pilot.pause()
            frames = [frame for frame in app.frames if frame[0] == owner]
            assert frames, "No activation frame captured"
            assert all(y == maximum and "LATEST-ACTIVITY" in text for _, y, maximum, text in frames), frames
            assert window.follows_tail
            app.frames = None
            # Intentional scroll-up is the exception: do not pull the reader to
            # the end when new activity arrives in another tab.
            window.scroll_relative(y=-8, animate=False, immediate=True)
            await pilot.pause()
            position = window.scroll_y
            assert not window.follows_tail
            await app.switch_mode(other.mode_name)
            await response.append("\n\nLATEST-WHILE-READING")
            await app.switch_mode(owner)
            await pilot.pause()
            assert not window.follows_tail and window.scroll_y == position
            # A page requested to fill a short tail can finish during activation.
            # Its temporary layout anchor must not turn follow mode into reading
            # mode or expose the old viewport before its restore callback runs.
            app.frames = None
            await conversation.contents.remove_children()
            cursor = TranscriptCursor("test", 100)
            page = TranscriptPage((TranscriptEvent("assistant", "LATEST-PAGED-ACTIVITY"),),
                                  cursor, cursor, True, False)
            started, release = asyncio.Event(), asyncio.Event()

            async def load_page(**kwargs):
                started.set()
                await release.wait()
                return TranscriptPage(
                    tuple(TranscriptEvent("assistant", f"Earlier activity {i}: " + "wrapped text " * 30)
                          for i in range(100)),
                    cursor, cursor, False, True,
                )

            history = TranscriptHistory(page, load_page)
            window.anchor()
            await conversation.contents.mount(history)
            async with asyncio.timeout(5):
                await started.wait()
            await app.switch_mode(other.mode_name)
            app.frames = []
            release.set()
            await app.switch_mode(owner)
            await pilot.pause()
            frames = [frame for frame in app.frames if frame[0] == owner]
            assert frames and all(y == maximum and "LATEST-PAGED-ACTIVITY" in text
                                  for _, y, maximum, text in frames), frames
            # Initial ACP replay also has to paint at the latest content. It
            # must not first show old records and then issue a deferred scroll.
            await conversation.contents.remove_children()
            snapshot = TranscriptPage(
                tuple(TranscriptEvent("assistant", f"Snapshot paragraph {i}") for i in range(100))
                + (TranscriptEvent("assistant", "LATEST-SNAPSHOT-ACTIVITY"),),
                cursor, cursor, True, False,
            )
            app.frames = []
            conversation.post_message(TranscriptSnapshot(snapshot.events, snapshot))
            async with asyncio.timeout(5):
                while not any("LATEST-SNAPSHOT-ACTIVITY" in frame[3] for frame in app.frames):
                    await asyncio.sleep(.02)
            await pilot.pause()
            painted = [frame for frame in app.frames
                       if "Snapshot paragraph" in frame[3] or "LATEST-SNAPSHOT-ACTIVITY" in frame[3]]
            assert painted and all(y == maximum and "LATEST-SNAPSHOT-ACTIVITY" in text
                                   for _, y, maximum, text in painted), painted
    print("thread activation: first painted frame is latest; deliberate scroll-up stays put")


if __name__ == "__main__":
    asyncio.run(main())
