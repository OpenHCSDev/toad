"""Fullscreen transitions must reflow and paint the transcript at its new width."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-resize-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        text = "## Resize test\n\n" + "A paragraph that wraps to the available viewport width. " * 80
        events = tuple(TranscriptEvent("assistant", f"Record {i}\n\n{text}") for i in range(20))
        page = TranscriptPage(events, TranscriptCursor("", 0), TranscriptCursor("", 0), False, False)

        async def load(**kwargs):
            raise AssertionError("No preceding file history in this fixture")

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(70, 25)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            await conversation.contents.remove_children()
            await conversation.post(TranscriptHistory(page, load))
            await conversation.post(AgentResponse("FINAL_VISIBLE_MARKER\n\n" + "Last paragraph. " * 10))
            conversation.window.anchor()
            await pilot.pause()
            for width, height in ((145, 28), (70, 25), (180, 50), (95, 35), (70, 25), (145, 28)):
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "FINAL_VISIBLE_MARKER" in frame, (
                    width, height, conversation.window.scroll_y, conversation.window.max_scroll_y,
                    conversation.contents.virtual_size, frame,
                )
                assert conversation.window.scroll_y <= conversation.window.max_scroll_y
            conversation.window.anchor(False)
            conversation.window.scroll_to(y=conversation.window.max_scroll_y // 2, animate=False, immediate=True)
            await pilot.pause()
            for width, height in ((70, 25), (145, 28), (95, 35), (180, 50), (70, 25)):
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert any(word in frame for word in ("paragraph", "Record", "Resize test")), (
                    width, height, conversation.window.scroll_y, conversation.window.max_scroll_y,
                    conversation.contents.virtual_size, frame,
                )
    print("resize rendering: fullscreen/windowed reflow preserves visible tail")


if __name__ == "__main__":
    asyncio.run(main())
