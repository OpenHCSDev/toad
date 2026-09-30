"""Actual conversation cursor must not author the transcript's scroll extent."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from toad.app import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main():
    with TemporaryDirectory(dir=".artifacts", prefix="cursor-extent-") as folder:
        root = Path(folder).resolve()
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
        )
        comms = Comms(root / "wire")
        comms.messaging.initialize_private_initial_protocol()
        journal = root / "saved-cursor-source.jsonl"
        def save(text):
            journal.write_text(json.dumps({"type": "message", "message": {
                "role": "assistant", "content": text,
            }}) + "\n")
        save("\n\n".join(f"Cursor extent paragraph {i}" for i in range(60)))
        comms.registry.declare(Thread("saved-cursor-source", frozenset(), str(root),
                                      session_file=str(journal)))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(139, 25)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            history = await view.post(TranscriptHistory(
                comms.transcripts.thread_transcript_page("saved-cursor-source"),
            ))
            await pilot.pause(0.5)
            view.window.scroll_end(animate=False, immediate=True)
            await pilot.pause(0.5)
            # The native binding selects the whole saved-history block.
            await pilot.press("alt+up")
            await pilot.pause(0.5)
            assert view.navigation.selected is history, "saved history not selected"
            before = {
                "scroll": view.window.scroll_y,
                "maximum": view.window.max_scroll_y,
                "selection": type(view.navigation.selected).__name__,
            }
            # Native update replaces the document body; End clears selection.
            save("CURRENT_BODY_MARKER short current response.")
            await history.update_live(comms.transcripts.thread_transcript_page("saved-cursor-source"))
            view.window.focus()
            await pilot.press("end")
            await pilot.pause(0.5)
            visible = view.screen._compositor.visible_widgets
            after = {
                "scroll": view.window.scroll_y,
                "maximum": view.window.max_scroll_y,
                "selection": type(view.navigation.selected).__name__,
                "history_visible": history in visible,
                "visible_bodies": sum(owner in visible for owner in view.window.document_viewport.owners),
                "extent": view.window.virtual_size.height,
            }
            print(json.dumps({"before": before, "after": after}, indent=2), flush=True)
            assert view.window.max_scroll_y == 0, after
            assert history in visible and after["visible_bodies"] > 0, after
            for size in ((70, 25), (180, 50)):
                await pilot.resize_terminal(*size)
                await pilot.pause(0.5)
                assert view.window.max_scroll_y == 0, (size, view.window.virtual_size)
                assert history in view.screen._compositor.visible_widgets, size
            assert app._exception is None


if __name__ == "__main__":
    asyncio.run(main())
