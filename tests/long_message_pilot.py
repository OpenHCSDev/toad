"""A large individual message scrolls automatically in bounded render fragments."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.transcript_history import TranscriptHistory, TranscriptFragmentView


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-long-message-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        text = "\n\n".join(f"Paragraph {i}: " + "read this automatically " * 12 for i in range(100))
        cursor = TranscriptCursor("", 0)
        page = TranscriptPage((TranscriptEvent("assistant", text),), cursor, cursor, False, False)
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(90, 35)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            await conversation.contents.remove_children()
            history = TranscriptHistory(page)
            await conversation.post(history)
            conversation.window.anchor()
            await pilot.pause()
            assert history.pages[0].start > 0
            assert len(history.query(TranscriptFragmentView)) <= 8
            while history.has_older:
                previous = history.pages[0].start
                conversation.window.scroll_home(animate=False, immediate=True)
                try:
                    async with asyncio.timeout(10):
                        while history.pages[0].start >= previous or history._loading:
                            await asyncio.sleep(.02)
                except TimeoutError:
                    print(previous, history.pages[0].start, history._loading,
                          history.window.scroll_y, history.window.max_scroll_y,
                          history.region, history.window.content_region)
                    raise
                await pilot.pause()
                assert len(history.query(TranscriptFragmentView)) <= max(history.MAX_FRAGMENTS, history.window.size.height * 2)
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            conversation.window.scroll_home(animate=False, immediate=True)
            await pilot.pause()
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Paragraph 0:" in frame
            history.newer.action_jump()
            await pilot.pause()
            frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Paragraph 99:" in frame
            # Semantic blocks may exceed the character budget. They must render
            # as leaves, never recursively page the same indivisible content.
            for block in (
                "A single long paragraph " * 150 + "PARAGRAPH-END",
                "```text\n" + "A long code line\n" * 150 + "CODE-END\n```",
                "\n".join(f"- list item {i} " + "more text " * 10 for i in range(40)) + " LIST-END",
            ):
                for response_type in (AgentResponse, AgentThought):
                    await conversation.contents.remove_children()
                    response = await conversation.post(response_type(block))
                    conversation.window.anchor()
                    await pilot.pause()
                    assert len(response.query(TranscriptHistory)) == 1
                    assert len(response.query(TranscriptFragmentView)) == 1
                    leaf = response.query_one(TranscriptFragmentView).query_one(response_type)
                    assert leaf.source == block and not leaf.query(TranscriptHistory)
                    assert not leaf.loading and leaf.size.height > 0
    print("long messages: automatic fragment paging, bounded widgets, and Jump to latest passed")


if __name__ == "__main__":
    asyncio.run(main())
