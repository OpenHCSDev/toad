"""Real native geometry borrows the worker's acquired source and styles."""

import asyncio
import json
import os

from agent_comms.comms import Comms
from textual.content import Content
from textual.color import Color
from textual.selection import SELECT_ALL
from toad.app import ToadApp
from toad.widgets.worker_static import WorkerStatic


def test_geometry_and_independent_source_style_selection(tmp_path, monkeypatch):
    async def mounted():
        project = tmp_path / "project"
        project.mkdir()
        service = Comms(tmp_path / "wire")
        service.messaging.initialize_private_initial_protocol()
        for key in tuple(os.environ):
            if key.startswith("AGENT_COMMS_"):
                monkeypatch.delenv(key)
        for key, value in {
            "AGENT_COMMS_ROOT": service.root, "XDG_CONFIG_HOME": tmp_path / "config",
            "XDG_STATE_HOME": tmp_path / "state", "XDG_DATA_HOME": tmp_path / "data",
            "XDG_CACHE_HOME": tmp_path / "cache",
        }.items():
            monkeypatch.setenv(key, str(value))
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            worker = WorkerStatic(Content.styled("Original native content " * 20, "$accent"))
            worker.styles.width = "auto"
            worker.styles.dock = "top"
            worker.styles.height = 4
            await app.selected_session.mount(worker)

            async def ready():
                await pilot.pause()
                async with asyncio.timeout(20):
                    await worker.wait_ready()
                assert worker.paint_ready and worker.prepared_content is not None

            await ready()
            acquired = worker._wanted.task.source
            for width in (95, 120, 100):
                await pilot.resize_terminal(width, 35)
                await ready()
                assert worker._wanted.task.source is acquired
                assert worker._wanted.task.presentation.options.size.width == width
                assert "Original native content" in worker.prepared_content.text
            worker.styles.color = "red"
            await ready()
            assert worker._wanted.task.presentation.native_style.foreground == Color.parse("red")
            app.screen.selections = {worker: SELECT_ALL}
            await ready()
            assert worker._wanted.task.source.selection is not None
            assert worker.get_selection(SELECT_ALL)[0] == worker._source.value.plain
            worker.update(Content("Changed native content " * 12))
            await ready()
            assert "Changed native content" in worker.prepared_content.text
            assert "Original native content" not in worker.prepared_content.text
            assert app._exception is None
            result = {"native_resizes": 3, "source_reused_on_geometry": True,
                      "style_selection_source_updates": True, "provider_inputs": 0}
            (tmp_path / "result.json").write_text(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)

    asyncio.run(mounted())


def test_tool_updates_leave_driver_input_available(tmp_path, monkeypatch):
    """Actual tool bodies, native Driver input and existing CPU workers."""
    import threading
    import time
    from acp.schema import ToolCall as NativeToolCall
    from rich.text import Text
    from textual import events
    from toad.acp.status import ToolCallStatus
    from toad.widgets.tool_call import ToolCall, ToolContent
    from toad.widgets.tool_content import TextContent

    async def mounted():
        project = tmp_path / "project"
        project.mkdir()
        service = Comms(tmp_path / "wire")
        service.messaging.initialize_private_initial_protocol()
        for key in tuple(os.environ):
            if key.startswith("AGENT_COMMS_"):
                monkeypatch.delenv(key)
        for key, value in {"AGENT_COMMS_ROOT": service.root,
                           "XDG_CONFIG_HOME": tmp_path / "config",
                           "XDG_STATE_HOME": tmp_path / "state",
                           "XDG_DATA_HOME": tmp_path / "data"}.items():
            monkeypatch.setenv(key, str(value))

        def update(text):
            return ToolCallStatus.from_acp(NativeToolCall.model_validate({
                "toolCallId": "owned-output", "title": "Original tool output",
                "status": "in_progress", "kind": "execute",
                "content": [{"type": "content", "content": {"type": "text", "text": text}}],
            }, strict=True))

        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            tool = await view.post(ToolCall(update("Initial output\n" * 50)))
            tool.set_expanded(True)
            await tool.output.sync()
            content = tool.query_one(TextContent)
            await asyncio.wait_for(content.wait_ready(), 20)
            await pilot.pause()
            tool.scroll_visible(animate=False, immediate=True)
            editor = view.prompt.prompt_text_area
            editor.focus(scroll_visible=False)
            text = "\x1b[31mOriginal ANSI output 界\x1b[0m\n" * 2000
            call = update(text)
            counts = {"ui_ansi_decodes": 0}
            main_thread = threading.get_ident()
            ansi_code = Text.from_ansi.__func__.__code__

            def trace(frame, event, argument):
                if (event == "call" and frame.f_code is ansi_code
                        and threading.get_ident() == main_thread):
                    counts["ui_ansi_decodes"] += 1

            threading.setprofile_all_threads(trace)
            started = time.monotonic()
            try:
                changing = asyncio.ensure_future(tool.update_tool_call(call))

                def input():
                    for key in "responsive":
                        app._driver.process_message(events.Key(key, key))
                        time.sleep(.008)

                await asyncio.to_thread(input)
                async with asyncio.timeout(20):
                    while "responsive" not in editor.text:
                        await asyncio.sleep(.005)
                input_ms = (time.monotonic() - started) * 1000
                await changing
                content = tool.query_one(TextContent)
                await asyncio.wait_for(content.wait_ready(), 20)
                assert content.prepared_content is not None
                assert "Original ANSI output" in content.prepared_content.text
                assert tool.query_one(ToolContent).native_body_ready()
                assert counts["ui_ansi_decodes"] == 0
            finally:
                threading.setprofile_all_threads(None)
            assert content.get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(Text.from_ansi(text).plain)
            window = view.window
            region = window.scrollable_content_region
            offset = region.offset + (region.width // 2, region.height // 2)
            before = window.scroll_y
            for _ in range(4):
                await pilot._post_mouse_events([events.MouseScrollDown], offset=offset)
            await pilot.wait_for_scheduled_animations()
            after = window.scroll_y
            assert after > before, "Original native wheel did not scroll the updated tool body"
            for _ in range(2):
                await pilot._post_mouse_events([events.MouseScrollUp], offset=offset)
            await pilot.wait_for_scheduled_animations()
            assert window.scroll_y < after, "Original native wheel reversal did not move"
            assert editor.text == "responsive"
            assert app._exception is None
            result = dict(counts, wheel_and_reversal=True, driver_draft=editor.text, driver_input_ms=input_ms,
                          rendered_lines=len(content.prepared_content.lines), provider_inputs=0,
                          scope="real source App/tool updates; no ACP transport or provider run")
            (tmp_path / "tool-update-result.json").write_text(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)

    asyncio.run(mounted())
