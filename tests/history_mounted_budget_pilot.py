"""Prepared history stays large while mounted work follows the visible viewport."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from agent_comms import TranscriptCursor, TranscriptEvent, TranscriptPage
from textual.selection import SELECT_ALL
from textual.widgets._markdown import MarkdownParagraph

from runtime_fixture import ToadApp
from toad.widgets.transcript_history import TranscriptHistory


async def main(observe):
    with tempfile.TemporaryDirectory(prefix="toad-mounted-budget-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(150, 80)) as pilot:
            await pilot.pause()
            events = tuple(TranscriptEvent("assistant", f"Record {index}\n\n" + "long paragraph words " * 28)
                           for index in range(120))
            cursor = TranscriptCursor("fixture", 0)
            page = TranscriptPage(events, cursor, cursor, False, False)
            history = TranscriptHistory(page)
            await app.screen.conversation.contents.mount(history)
            await pilot.pause()
            window = history.window
            window.release_anchor()
            mounted = []
            durations = []
            with patch.object(history, "_check_edges", lambda: None):
                for _ in range(20):
                    window.scroll_to(y=1, animate=False, immediate=True)
                    await pilot.pause()
                    begin = time.perf_counter()
                    await history._load_page(True)
                    await pilot.pause()
                    durations.append((time.perf_counter()-begin)*1000)
                    mounted.append(history.fragment_count)
                if not observe:
                    assert max(mounted) <= 32, mounted
                assert history.pages[0].page.events == events, "Source history was truncated"
                print(json.dumps({"peak_mounted_before_selection": max(mounted),
                                  "widgets_before_selection": history.widget_count}), flush=True)
                # A selected fragment away from the new viewport must survive
                # later admission and trimming, including native text copying.
                chosen = history.pages[0].children[-1]
                text = chosen.query_one(MarkdownParagraph)
                expected = text.render().plain
                app.screen.selections = {text: SELECT_ALL}
                start = history.pages[0].start
                for _ in range(3):
                    window.scroll_to(y=1, animate=False, immediate=True)
                    await pilot.pause()
                    await history._load_page(True)
                    await pilot.pause()
                assert history.pages[0].start < start, "Selection stopped earlier-page admission"
                assert text.is_attached and expected in app.screen.get_selected_text()
                app.screen.clear_selection()
            assert app._exception is None
            print(json.dumps({"boundary": "headless page admission plus pilot settlement, not terminal pixels",
                              "peak_mounted_fragments": max(mounted), "final_widgets": history.widget_count,
                              "admissions": len(durations), "max_admission_ms": round(max(durations), 2)}))
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", action="store_true")
    asyncio.run(main(parser.parse_args().observe))
