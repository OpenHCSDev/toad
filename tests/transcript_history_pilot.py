"""Scroll both directions through a bounded replay window without losing history."""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agent_comms.threads import Thread
from agent_comms.comms import wire
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory
from toad.render_tasks import TranscriptBodyPreparation


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
        comms.registry.declare(Thread("worker", frozenset(), str(root), session_file=str(path)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            conversation = app.selected_session.conversation
            await conversation.contents.remove_children()

            async def load(**kwargs):
                return await asyncio.to_thread(comms.transcripts.thread_transcript_page, "worker", **kwargs)

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
                        (not history.state.accepts_source_work), history._check_pending, history.window.follows_tail,
                        history.window.scroll_y, history.window.max_scroll_y,
                        history.region, history.window.content_region,
                    )) from None
                await pilot.pause()
                await until(lambda: history.state.accepts_source_work)
                assert len(history.pages) <= history.fragment_limit
                assert history.fragment_count <= history.fragment_limit
                assert len(history.query("AgentResponse")) <= history.fragment_limit
            assert history.pages[0].page.events[0].text.startswith("Record 0\n")
            # Exercise the actual decoded source and shared renderer before
            # navigation consumes its prepared bodies. All MRO handlers,
            # including the undisclosed base, obey the async dispatch contract.
            preparation = TranscriptBodyPreparation(
                app.render_processes, app.native_ansi_color, app.current_theme.dark,
            )
            for event in history.pages[0].page.events:
                await preparation.dispatch(event)
            # End addresses the native source tail rather than each intervening
            # admitted page. Actual key delivery must work during an edge read.
            while history.pages[-1].stop < len(history.pages[-1].fragments):
                history._request_page(False)
                await until(lambda: history.state.accepts_source_work)
                await pilot.pause()
            assert history.pages[-1].page.has_newer
            entered, release = asyncio.Event(), asyncio.Event()
            original_loader = history.loader

            async def delayed_load(**kwargs):
                entered.set()
                await release.wait()
                return await original_loader(**kwargs)

            history.loader = delayed_load
            history._request_page(False)
            await entered.wait()
            conversation.window.focus()
            await pilot.press("end")
            release.set()
            await until(lambda: history.state.accepts_source_work and not history.has_newer)
            await pilot.pause()
            assert conversation.window.follows_tail
            assert conversation.window.scroll_y == conversation.window.max_scroll_y
            assert len(history.pages) == 1
            assert history.fragment_count <= history.fragment_limit
            assert history.pages[-1].page.events[-1].text.startswith("Record 104\n")
            region = conversation.window.scrollable_content_region
            painted = "\n".join(strip.crop(region.x, region.right).text for strip in
                                app.screen._compositor.render_strips()[region.y:region.bottom])
            assert "Record 104" in painted, painted
    print("transcript history: scroll to first record and back, bounded DOM and adjacent cursors passed")


if __name__ == "__main__":
    asyncio.run(main())
