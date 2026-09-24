"""File preview preparation stays off-loop and uses the shared renderer API."""

import asyncio
import os
from pathlib import Path
import tempfile
from threading import Event
from typing import TypeVar
from unittest.mock import patch

from rich.segment import Segment
from rich.syntax import Syntax
from rich.table import Table
from textual.strip import Strip
from textual.selection import SELECT_ALL
from textual.widget import _Styled

from runtime_fixture import ToadApp
from toad.render_backend import Renderer
from toad.render_processes import RenderProcessPool
from toad.render_tasks import RenderTask, RichRenderTask
from toad.rich_preparation import SyntaxSource
from toad.widgets.project_panel import FilePreview
from toad.widgets.worker_static import WorkerStatic

ResultT = TypeVar("ResultT")


class GateRenderer(Renderer):
    def __init__(self):
        RenderProcessPool.prepare_spawn()
        self.pool = RenderProcessPool()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.requests = []

    async def submit(self, task: RenderTask[ResultT]) -> ResultT:
        if isinstance(task, RichRenderTask):
            self.requests.append(task)
            self.entered.set()
            await self.release.wait()
        return await self.pool.submit(task)

    async def aclose(self) -> None:
        self.release.set()
        await self.pool.aclose()


async def main():
    RenderProcessPool.prepare_spawn()
    with tempfile.TemporaryDirectory(prefix="toad-worker-preview-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        source = "# café 界\n" + "def original(value: int) -> int:\n    return value + 1\n\n" * 1500
        path = root / "preview.py"
        path.write_text(source)
        renderer = GateRenderer()
        app = ToadApp(project_dir=str(root), renderer=renderer)
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            prompt = app.screen.conversation.prompt

            # Even file IO cannot hold mode mounting or prevent leaving the tab.
            entered, release = Event(), Event()
            original_read = FilePreview._read_prefix

            def blocked_read(path, limit):
                entered.set()
                if not release.wait(8):
                    raise TimeoutError("Test did not release file IO")
                return original_read(path, limit)

            try:
                with patch.object(FilePreview, "_read_prefix", staticmethod(blocked_read)):
                    mode = await asyncio.wait_for(app.open_file_preview(path), 2)
                    assert await asyncio.to_thread(entered.wait, 2)
                    await asyncio.wait_for(app.switch_mode(owner), 2)
                    prompt.focus()
                    await pilot.press("i", "o")
                    assert prompt.text == "io"
                    await app.close_session_mode(mode)
            finally:
                release.set()

            # The normal default component submits Rich work; no syntax function
            # is allowed to run in this UI process, including lexer discovery.
            with (patch.object(Syntax, "guess_lexer", side_effect=AssertionError("UI lexer discovery")),
                  patch.object(Syntax, "highlight", side_effect=AssertionError("UI highlighting"))):
                mode = await asyncio.wait_for(app.open_file_preview(path), 2)
                preview = app.screen.query_one(FilePreview)
                await asyncio.wait_for(renderer.entered.wait(), 4)
                widget = preview.query_one(WorkerStatic)
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "Preparing preview" in frame or "Loading file" in frame
                assert not widget._ready.is_set()
                await app.switch_mode(owner)
                prompt.focus()
                await pilot.press("w", "o", "r", "k")
                assert prompt.text == "iowork" and not renderer.release.is_set()
                await app.switch_mode(mode)
                renderer.release.set()
                await asyncio.wait_for(preview.wait_ready(), 20)
                await pilot.pause()
                assert widget._prepared is not None
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "def original" in frame, frame
                with patch.object(widget, "render_line", wraps=widget.render_line) as rendered:
                    widget.refresh()
                    await pilot.pause()
                    assert 0 < rendered.call_count < app.size.height * 4, "Repaint walked the complete code document"
                calls = len(renderer.requests)
                await app.switch_mode(owner)
                await app.switch_mode(mode)
                await pilot.pause()
                assert len(renderer.requests) == calls, "Unchanged tab return rerendered the document"
                await app.close_session_mode(mode)

            for name, data, expected in (("binary.bin", b"\x00binary", "binary file"),
                                         ("missing.py", None, "Unable to open")):
                file = root / name
                if data is not None:
                    file.write_bytes(data)
                mode = await app.open_file_preview(file)
                preview = app.screen.query_one(FilePreview)
                await asyncio.wait_for(preview.wait_ready(), 3)
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert expected in frame
                await app.close_session_mode(mode)

            # Any data-only Rich renderable can use the same component/task.
            table = Table("Name", "Value", box=None)
            table.add_row("generic", "42")
            generic = WorkerStatic(table)
            await app.screen.mount(generic)
            await asyncio.wait_for(generic.wait_ready(), 10)
            await pilot.pause()
            assert generic._prepared is not None
            assert any("generic" in line.text for line in generic._prepared.lines)

            # Source/width changes while pending coalesce; obsolete results are
            # discarded instead of repainting the previous source after a delay.
            renderer.entered.clear()
            renderer.release.clear()
            generic.update(SyntaxSource("OLD_SOURCE = 1\n", "update.py"))
            await asyncio.wait_for(renderer.entered.wait(), 2)
            generic.update(SyntaxSource("LATEST_SOURCE = 2\n", "update.py"))
            await pilot.resize_terminal(90, 32)
            renderer.release.set()
            await asyncio.wait_for(generic.wait_ready(), 10)
            await pilot.pause()
            assert generic._prepared is not None
            assert "LATEST_SOURCE" in "\n".join(line.text for line in generic._prepared.lines)
            request = generic._ready_request.task
            expected = tuple(Strip(line) for line in Segment.split_and_crop_lines(
                app.console.render(
                    _Styled(request.source.materialize(), request.presentation.base_style,
                            request.presentation.link_style),
                    request.presentation.options.update(width=generic._prepared.width, height=None, highlight=False),
                ), generic._prepared.width, include_new_lines=False, pad=False,
            ))
            assert generic._prepared.lines == expected, (
                "Worker output differs from native Rich", [list(line) for line in generic._prepared.lines[:2]],
                [list(line) for line in expected[:2]],
            )
            # Reverting a width while its replacement is pending must restore
            # the already-ready intent, not later publish the abandoned width.
            current = generic._ready_request
            renderer.entered.clear()
            renderer.release.clear()
            await pilot.resize_terminal(105, 32)
            await asyncio.wait_for(renderer.entered.wait(), 2)
            await pilot.resize_terminal(90, 32)
            await asyncio.wait_for(generic.wait_ready(), 2)
            assert generic._ready_request == current
            renderer.release.set()
            async with asyncio.timeout(10):
                while generic._preparing:
                    await asyncio.sleep(.01)
            assert generic._ready_request == current
            app.screen.selections = {generic: SELECT_ALL}
            selected = generic.render_line(0)
            assert any(segment.style and segment.style.meta.get("offset") is not None for segment in selected)
            assert "LATEST_SOURCE" in generic.get_selection(SELECT_ALL)[0]
            app.screen.selections = {}
            for theme in ("textual-light", "ansi-dark"):
                app.theme = theme
                await pilot.pause()
                await asyncio.wait_for(generic.wait_ready(), 10)
                await pilot.pause()
                assert generic._ready_request.task.presentation.base_style == generic.visual_style.rich_style
            renderer.entered.clear()
            renderer.release.clear()
            generic.set_source(SyntaxSource("CLOSED_SOURCE = 3\n", "closed.py"))
            await asyncio.wait_for(renderer.entered.wait(), 2)
            await generic.remove()
            renderer.release.set()
            await pilot.pause()
            assert generic._prepared is None and app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("worker preview: IO/CPU waits preserve typing/navigation, native Rich parity, generic content, stable returns, stale/closed results OK")


if __name__ == "__main__":
    asyncio.run(main())
