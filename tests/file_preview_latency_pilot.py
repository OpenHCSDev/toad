"""Compare original native preview loading and default worker-backed preview."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from rich.syntax import Syntax
from textual.containers import VerticalScroll
from textual.widgets import Static

from runtime_fixture import ToadApp
from toad.screens import file_preview
from toad.widgets.project_panel import FilePreview


class NativePreview(VerticalScroll):
    """The old main-thread Syntax path, retained only as a benchmark control."""

    DEFAULT_CSS = FilePreview.DEFAULT_CSS.replace("FilePreview", "NativePreview")

    def __init__(self, path, *, id):
        super().__init__(id=id)
        self.path = path
        self.ready = asyncio.Event()

    async def on_mount(self):
        await self.mount(Static(str(self.path), classes="file-preview-path"))
        data = await asyncio.to_thread(FilePreview._read_prefix, self.path, FilePreview.MAX_BYTES + 1)
        text = data.decode("utf-8", errors="replace")
        lexer = Syntax.guess_lexer(str(self.path), text)
        await self.mount(Static(Syntax(text, lexer, line_numbers=True, word_wrap=False, background_color="default")))
        self.ready.set()

    async def wait_ready(self):
        await self.ready.wait()


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-preview-latency-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        source = "# PREVIEW_MARKER café 界\n" + "def calculate(value: int) -> int:\n    return value + 1\n\n" * 1500
        app = ToadApp(project_dir=str(root))
        reports = []
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            for index, (name, widget_type) in enumerate((("native", NativePreview), ("worker", FilePreview)) * 2):
                path = root / f"{name}-{index}.py"
                path.write_text(source)
                gaps = []

                async def heartbeat():
                    previous = time.perf_counter()
                    while True:
                        await asyncio.sleep(.005)
                        now = time.perf_counter()
                        gaps.append(now - previous)
                        previous = now

                pulse = asyncio.create_task(heartbeat())
                await asyncio.sleep(0)
                started = time.perf_counter()
                cpu = time.thread_time()
                try:
                    with patch.object(file_preview, "FilePreview", widget_type):
                        mode = await app.open_file_preview(path)
                        opened = time.perf_counter() - started
                        await asyncio.wait_for(app.screen.query_one(widget_type).wait_ready(), 30)
                        await pilot.pause()
                        ready = time.perf_counter() - started
                        main_cpu = time.thread_time() - cpu
                        frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                        assert "PREVIEW_MARKER" in frame and "def calculate" in frame
                finally:
                    pulse.cancel()
                    await asyncio.gather(pulse, return_exceptions=True)
                reports.append({"case": name, "round": index // 2, "source_bytes": len(source.encode()),
                                "open_handler_ms": round(opened * 1000, 2),
                                "ready_ms": round(ready * 1000, 2),
                                "ui_thread_cpu_ms": round(main_cpu * 1000, 2),
                                "max_event_loop_gap_ms": round(max(gaps) * 1000, 2)})
                await app.close_session_mode(mode)
                await pilot.pause()
            print(json.dumps({"boundary": "headless ready content + event-loop heartbeat; not terminal pixels",
                              "samples": reports}, indent=2))
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
