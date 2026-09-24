"""Scroll both directions through a bounded replay window without losing history."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-history-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        path = root / "session.jsonl"
        path.write_text("".join(json.dumps({"type": "message", "message": {
            "role": "assistant", "content": f"Record {i}\n\nContent."
        }}) + "\n" for i in range(105)))
        comms = wire(root / "wire")
        comms.register(Thread("worker", frozenset(), str(root), session_file=str(path)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            await conversation.contents.remove_children()

            async def load(**kwargs):
                return await asyncio.to_thread(comms.thread_transcript_page, "worker", **kwargs)

            history = TranscriptHistory(await load(), load)
            await conversation.post(history)
            conversation.window.scroll_end(animate=False, immediate=True)
            await pilot.pause()
            while history.older.display:
                position = (history.pages[0].page.before.offset, history.pages[0].start)
                conversation.window.scroll_home(animate=False, immediate=True)
                try:
                    await until(lambda: (history.pages[0].page.before.offset, history.pages[0].start) < position)
                except TimeoutError:
                    raise AssertionError((
                        position, [(p.page.before.offset, p.start, p.stop) for p in history.pages],
                        history._loading, history._check_pending, history.window.follows_tail,
                        history.window.scroll_y, history.window.max_scroll_y,
                        history.region, history.window.content_region,
                    )) from None
                await pilot.pause()
                await until(lambda: not history._loading)
                assert len(history.pages) <= history.fragment_limit
                assert history.fragment_count <= history.fragment_limit
                assert len(history.query("AgentResponse")) <= history.fragment_limit
            assert history.pages[0].page.events[0].text.startswith("Record 0\n")
            while history.newer.display:
                position = (history.pages[-1].page.after.offset, history.pages[-1].stop)
                conversation.window.scroll_end(animate=False, immediate=True)
                await until(lambda: (history.pages[-1].page.after.offset, history.pages[-1].stop) > position)
                await pilot.pause()
                await until(lambda: not history._loading)
                assert len(history.pages) <= history.fragment_limit
                assert history.fragment_count <= history.fragment_limit
            assert history.pages[-1].page.events[-1].text.startswith("Record 104\n")
    print("transcript history: scroll to first record and back, bounded DOM and adjacent cursors passed")


if __name__ == "__main__":
    asyncio.run(main())
