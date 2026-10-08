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


def test_history_publication_scope_owns_native_fence_and_releases_on_cancel(tmp_path, monkeypatch):
    from toad.widgets.note import Note

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
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(100, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            window = view.window
            first, second = Note("First original row"), Note("Second original row")
            await view.contents.mount(first, second)
            await pilot.pause()
            async with window.preserve_history(None, root=first):
                assert window.history_mutation_root is first
                assert first in app.screen._layout_mutation_roots()
                assert window not in app.screen._layout_mutation_roots()
                async with window.preserve_history(None, root=second):
                    assert window.history_mutation_root is view.contents
                assert window.history_mutation_root is first
            assert window.history_mutation_root is None

            entered = asyncio.Event()
            async def pending_publication():
                async with window.preserve_history(None, root=first):
                    entered.set()
                    await asyncio.Event().wait()
            publication = asyncio.create_task(pending_publication())
            await entered.wait()
            publication.cancel()
            result = await asyncio.gather(publication, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
            assert window.history_mutation_root is None
            assert not window.lock.is_locked
            async with window.lock:
                assert window.history_mutation_root is window
            assert window.history_mutation_root is None
            assert app._exception is None

    asyncio.run(mounted())


def test_prepared_measurement_ignores_parent_height_and_invalidates_source(tmp_path, monkeypatch):
    """Native measurement borrows rows; source publication changes their extent."""
    from textual._measurement import NATIVE_WIDGET_HEIGHT, NATIVE_WIDGET_WIDTH
    from textual.geometry import Size
    from toad.widgets.prepared_markdown import PreparedParagraph, PreparedH1
    from toad.widgets.tool_content import TextContent
    from toad.widgets.irc_message import IRCMessageText

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
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(100, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            worker = WorkerStatic(Content("Original prepared row"))
            worker.styles.width = 40
            worker.styles.height = "auto"
            await app.selected_session.mount(worker)
            await asyncio.wait_for(worker.wait_ready(), 20)
            await pilot.pause()
            for cls in (WorkerStatic, PreparedParagraph, PreparedH1, TextContent, IRCMessageText):
                assert cls._content_height_dependency is NATIVE_WIDGET_HEIGHT
                assert cls._content_width_dependency is NATIVE_WIDGET_WIDTH
            assert not worker._content_height_dependency.depends(worker)
            assert not worker._content_width_dependency.depends(worker)
            prepared = worker.prepared_content
            request = worker._wanted
            width = request.task.presentation.options.max_width
            for height in (10, 100, 1000):
                box = Size(width, height)
                assert worker.get_content_height(box, box, width) == len(prepared.lines)
                assert worker.get_content_width(box, box) == prepared.width
                assert worker._wanted is request
                assert worker.prepared_content is prepared
            for tentative_width in (width // 2, width * 2, width):
                box = Size(tentative_width, 100)
                assert worker.get_content_height(box, box, tentative_width) == len(prepared.lines)
                assert worker._wanted is request
                assert worker.prepared_content is prepared
            worker.update(Content("Changed row\n" * 30))
            await asyncio.wait_for(worker.wait_ready(), 20)
            await pilot.pause()
            assert worker.prepared_content is not prepared
            assert len(worker.prepared_content.lines) > len(prepared.lines)
            assert worker.get_content_height(Size(width, 10), Size(width, 10), width) == len(worker.prepared_content.lines)
            assert app._exception is None
            print("Native worker measurements preserved rows across parent heights; source update changed extent.", flush=True)

    asyncio.run(mounted())


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
    from textual.geometry import Offset
    from textual.selection import Selection
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
            line = "Original ANSI output 界 " + "wrapping " * 20
            original_plain = (line + "\n") * 2000
            text = ("\x1b[31m" + line + "\x1b[0m\n") * 2000
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
                assert content.prepared_content.original_text == original_plain
                assert len(content.prepared_content.lines) > 2000
                assert content.get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(original_plain)
                selection = Selection(Offset(9, 0), Offset(22, 2))
                assert content.get_selection(selection)[0] == selection.extract(original_plain)
                assert counts["ui_ansi_decodes"] == 0
            finally:
                threading.setprofile_all_threads(None)
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
            result = dict(counts, source_coordinate_copy=True, wheel_and_reversal=True, driver_draft=editor.text, driver_input_ms=input_ms,
                          rendered_lines=len(content.prepared_content.lines), provider_inputs=0,
                          scope="real source App/tool updates; no ACP transport or provider run")
            (tmp_path / "tool-update-result.json").write_text(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)

    asyncio.run(mounted())


def test_active_markdown_acquires_inline_content_off_ui(tmp_path, monkeypatch):
    """Actual LiveOutput, paged Markdown, native blocks and Driver input."""
    import threading
    import time
    from textual import events
    from textual.widgets._markdown import MarkdownBlock, MarkdownHeader, MarkdownTable
    from toad.live_output import ResponseStream
    from viewport_recent_tabs_pilot import settled
    from sidebar_retirement_pilot import viewport_text
    from toad.widgets.prepared_markdown import PreparedConversationMarkdown

    async def mounted():
        project = tmp_path / "project"
        project.mkdir()
        (project / "source.py").write_text("value = 1\n")
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
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            editor = view.prompt.prompt_text_area
            editor.focus(scroll_visible=False)
            counts = {"ui_inline_conversions": 0, "worker_inline_conversions": 0}
            main_thread = threading.get_ident()
            conversion = MarkdownBlock._token_to_content.__code__

            def trace(frame, event, argument):
                if event == "call" and frame.f_code is conversion:
                    key = ("ui_inline_conversions" if threading.get_ident() == main_thread
                           else "worker_inline_conversions")
                    counts[key] += 1

            chunks = ["# Original heading 界\n\n"]
            chunks += [
                (f"## Update {index}\n\n" +
                 "An **original** *styled* `value` with [project source](source.py). " * 20 +
                 "\n\n| Original header | Native value |\n| --- | --- |\n" +
                 f"| row {index} | **界** [source](source.py) |\n\n")
                for index in range(4)
            ]
            async def updates():
                body = None
                for chunk in chunks:
                    body = await view.output.append(ResponseStream(turn_id="private-source-update"), chunk)
                    await asyncio.sleep(.03)
                await view.output.finish(ResponseStream)
                return body

            threading.setprofile_all_threads(trace)
            started = time.monotonic()
            try:
                changing = asyncio.create_task(updates())
                def input():
                    for key in "active draft":
                        app._driver.process_message(events.Key(key, key))
                        time.sleep(.01)
                await asyncio.to_thread(input)
                async with asyncio.timeout(20):
                    while editor.text != "active draft":
                        await asyncio.sleep(.005)
                input_ms = (time.monotonic() - started) * 1000
                body = await asyncio.wait_for(changing, 20)
                async with asyncio.timeout(20):
                    while not body.body_ready:
                        await pilot.pause(.02)
                assert body.source == "".join(chunks)
                assert body.fragments and body.fragment_views
                headings = tuple(body.query(MarkdownHeader))
                tables = tuple(body.query(MarkdownTable))
                assert headings and tables
                assert any("Update" in heading._content.plain for heading in headings)
                assert any("Original header" in cell.plain
                           for table in tables for cell in table._headers)
                resources = tuple(markdown._prepared_markdown for markdown in
                                  body.query(PreparedConversationMarkdown)
                                  if markdown._prepared_markdown is not None)
                assert resources and all(resource.inlines for resource in resources)
                assert any(span.style.meta.get("@click", "")
                           for resource in resources for content in resource.inlines.values()
                           for span in content.spans if not isinstance(span.style, str))
                assert counts["ui_inline_conversions"] == 0
                assert counts["worker_inline_conversions"] > 0
            finally:
                threading.setprofile_all_threads(None)
            await settled(pilot, view)
            window = view.window
            region = window.scrollable_content_region
            offset = region.offset + (region.width // 2, region.height // 2)
            before_paint = viewport_text(window)
            assert before_paint.strip()
            for _ in range(4):
                await pilot._post_mouse_events([events.MouseScrollUp], offset=offset)
            await pilot.wait_for_scheduled_animations()
            await settled(pilot, view)
            up_paint = viewport_text(window)
            assert up_paint.strip() and up_paint != before_paint
            assert not window.follows_tail
            for _ in range(2):
                await pilot._post_mouse_events([events.MouseScrollDown], offset=offset)
            await pilot.wait_for_scheduled_animations()
            await settled(pilot, view)
            reverse_paint = viewport_text(window)
            assert reverse_paint.strip() and reverse_paint != up_paint
            assert editor.text == "active draft"
            assert app._exception is None
            result = dict(counts, driver_input_ms=input_ms, source_characters=len(body.source),
                          heading_table_links=True, wheel_reversal_draft=True, provider_inputs=0,
                          scope="source App/LiveOutput/paged native admission; no ACP transport/provider")
            (tmp_path / "markdown-update-result.json").write_text(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)

    asyncio.run(mounted())


def test_active_markdown_retains_paint_until_current_source_commits(tmp_path, monkeypatch):
    """An open conversation borrows preceding paint without admitting stale source."""
    from textual import events
    from toad.rich_preparation import ContentSource, RenderableSource
    from toad.widgets.agent_response import AgentResponse
    from toad.widgets.prepared_markdown import PreparedParagraph
    from rich.text import Text

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
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            document = AgentResponse("Original response", paginate=False)
            await view.post(document)
            await document.update("Original response")
            paragraph = document.query_one(PreparedParagraph)
            await asyncio.wait_for(paragraph.wait_ready(), 20)
            await pilot.pause()
            prepared, request = paragraph.prepared_content, paragraph._ready_request
            original = paragraph._content
            for _ in range(20):
                paragraph.set_content(original)
            assert paragraph._generation == request.generation
            assert paragraph._wanted == request
            assert paragraph.prepared_content is prepared
            assert paragraph.preparation_complete and paragraph.paint_ready

            changed = Content.styled("Changed response 界", "bold red")
            paragraph.set_content(changed)
            assert paragraph._prepared is prepared
            assert paragraph._ready_request is request
            assert not paragraph.paint_ready and not paragraph.preparation_complete
            assert paragraph.presentation_ready and document.body_ready
            assert paragraph.prepared_content is None
            assert paragraph.get_selection(SELECT_ALL)[0] == original.plain
            assert "Preparing preview" not in paragraph.render_line(0).text
            editor = view.prompt.prompt_text_area
            editor.focus(scroll_visible=False)
            for key in "kept draft":
                app._driver.process_message(events.Key(key, key))
            await asyncio.wait_for(paragraph.wait_ready(), 20)
            await pilot.pause()
            assert paragraph.paint_ready and paragraph.preparation_complete
            assert paragraph.get_selection(SELECT_ALL)[0] == changed.plain
            assert paragraph.prepared_content is not prepared
            assert editor.text == "kept draft"

            # Native Content.__eq__ omits spans. Formatting/action changes are
            # independent source answers even when plain text stays identical.
            generation = paragraph._generation
            paragraph.set_content(Content.styled(changed.plain, "italic blue"))
            assert paragraph._generation == generation + 1
            assert not paragraph.paint_ready
            await asyncio.wait_for(paragraph.wait_ready(), 20)
            await pilot.resize_terminal(95, 35)
            await pilot.pause()
            await asyncio.wait_for(paragraph.wait_ready(), 20)
            assert paragraph._wanted.task.presentation.options.max_width > 0
            assert paragraph.paint_ready
            assert not RenderableSource(Text("mutable")).same_source(RenderableSource(Text("mutable")))
            assert not ContentSource(changed).same_source(ContentSource(Content(changed.plain)))
            assert app._exception is None
            result = {"unchanged_native_updates": 20, "prepared_identity_retained": True,
                      "pending_source_not_ready": True, "displayed_source_copy": True,
                      "changed_spans_reprepared": True, "driver_draft": editor.text,
                      "provider_inputs": 0, "scope": "open source App/native Markdown; no ACP/provider"}
            (tmp_path / "retained-markdown-paint.json").write_text(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)

    asyncio.run(mounted())


def test_paged_nested_markdown_publishes_visible_preparation(tmp_path, monkeypatch):
    """Real paged bodies publish worker text through their original native reader."""
    import time
    from textual import events
    from toad.widgets.agent_response import AgentResponse
    from toad.widgets.prepared_markdown import PreparedMarkdownContent
    from toad.rich_preparation import PreparedPaintSource
    from toad.widgets.viewport_body import MeasuredViewportBody, RenderedBody
    from textual.walk import walk_depth_first
    from viewport_recent_tabs_pilot import settled
    from sidebar_retirement_pilot import viewport_text

    async def mounted():
        project = tmp_path / "project"
        project.mkdir()
        (project / "source.py").write_text("value = 1\n")
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
        source = "\n\n".join(
            f"## Saved section {i}\n\nOriginal paragraph 界 [source](source.py).\n\n"
            "- Original parent **text** and [project link](source.py)\n"
            "  - Nested child *text* and [web link](https://example.com)\n"
            "    - Deep child with `original coordinates`\n"
            for i in range(24)
        )
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            document = AgentResponse(source)
            started = time.monotonic()
            await view.post(document)
            await document.update(source)
            await settled(pilot, view)
            async with asyncio.timeout(20):
                while not document.body_ready:
                    await pilot.pause(.02)
            ready_ms = (time.monotonic() - started) * 1000
            assert document.fragments and document.fragment_views
            from toad.widgets.transcript_history import TranscriptHistory
            assert not tuple(walk_depth_first(document, TranscriptHistory, with_root=False))
            assert not tuple(walk_depth_first(document, AgentResponse, with_root=False))
            window = view.window
            window.release_anchor()
            window.scroll_home(animate=False, immediate=True)
            await settled(pilot, view)
            # Live body readiness admits native layout. Worker paint has its
            # own original after-refresh publication, which retention borrows.
            # A retired placeholder has no remaining worker and still fails
            # the actual paint assertions below.
            async with asyncio.timeout(20):
                while any(widget.prepared_content is None
                          for widget in app.screen._compositor.visible_widgets
                          if isinstance(widget, PreparedPaintSource)):
                    await pilot.pause(.02)
            await settled(pilot, view)
            paint = viewport_text(window)
            assert "Saved section" in paint and "Original parent" in paint
            assert "Preparing preview" not in paint
            ready = tuple(block for block in walk_depth_first(document, PreparedMarkdownContent)
                          if block.paint_ready and block.prepared_content is not None)
            retained = tuple((body, body._body_measurement.content)
                             for body in walk_depth_first(window)
                             if isinstance(body, MeasuredViewportBody)
                             and isinstance(body._body_measurement, RenderedBody))
            assert ready or retained
            assert (any(span.style.meta.get("@click", "")
                        for block in ready for span in block._ready_request.task.source.value.spans
                        if not isinstance(span.style, str))
                    or any(segment.style and segment.style.meta.get("@click", "")
                           for body, content in retained for strip in content.lines
                           for segment in strip))
            for block in ready:
                assert block.get_selection(SELECT_ALL)[0] == block._ready_request.task.source.value.plain
            for body, content in retained:
                assert body.get_selection(SELECT_ALL)[0] == content.text
            region = window.scrollable_content_region
            offset = region.offset + (region.width // 2, region.height // 2)
            before = window.scroll_y
            for _ in range(16):
                await pilot._post_mouse_events([events.MouseScrollDown], offset=offset)
            await pilot.wait_for_scheduled_animations()
            down = window.scroll_y
            for _ in range(8):
                await pilot._post_mouse_events([events.MouseScrollUp], offset=offset)
            await pilot.wait_for_scheduled_animations()
            reverse = window.scroll_y
            await settled(pilot, view)
            assert down > before and reverse < down
            async with asyncio.timeout(20):
                while any(widget.prepared_content is None
                          for widget in app.screen._compositor.visible_widgets
                          if isinstance(widget, PreparedPaintSource)):
                    await pilot.pause(.02)
            await settled(pilot, view)
            assert "Preparing preview" not in viewport_text(window)
            retained = tuple(body._body_measurement.content
                             for body in walk_depth_first(window)
                             if isinstance(body, MeasuredViewportBody)
                             and isinstance(body._body_measurement, RenderedBody))
            assert all("Preparing preview" not in content.text for content in retained)
            stopped = window.scroll_y
            await pilot.pause(.2)
            assert window.scroll_y == stopped
            # The paged response is one viewport owner. Its internal fragments
            # cannot retire independently while their enclosing body is visible.
            # Move the original body offscreen through another real response.
            following_source = "\n\n".join(f"Following response paragraph {i}" for i in range(40))
            following = AgentResponse(following_source)
            await view.post(following)
            await following.update(following_source)
            window.release_anchor()
            window.scroll_end(animate=False, immediate=True)
            await settled(pilot, view)
            async with asyncio.timeout(20):
                while not isinstance(document._body_measurement, RenderedBody):
                    await pilot.pause(.02)
            captured = document._body_measurement.content
            assert "Preparing preview" not in captured.text
            assert "Original parent" in captured.text and "Saved section" in captured.text
            assert not tuple(walk_depth_first(document, PreparedPaintSource))
            assert any(segment.style and segment.style.meta.get("@click", "")
                       for strip in captured.lines for segment in strip)
            assert document.get_selection(SELECT_ALL)[0] == captured.text
            document.scroll_visible(animate=False, immediate=True)
            await settled(pilot, view)
            assert document._body_measurement.content is captured
            assert "Preparing preview" not in viewport_text(window)
            assert app._exception is None
            result = {"paged": True, "sections": 24, "ready_ms": ready_ms,
                      "visible_nested_text": True, "links_and_source_copy": True,
                      "retired_source_not_preview": True, "warm_paint_identity": True,
                      "native_wheel_reverse_stop": True, "provider_inputs": 0,
                      "scope": "source Toad App/paged authored Markdown; not saved SDK acceptance"}
            (tmp_path / "paged-markdown-result.json").write_text(json.dumps(result) + "\n")
            print(json.dumps(result), flush=True)

    asyncio.run(mounted())


def test_custom_markdown_block_keeps_its_bound_conversion(tmp_path, monkeypatch):
    """A native extension may depend on its actual document and block identity."""
    from toad.widgets.prepared_markdown import PreparedConversationMarkdown, PreparedParagraph
    from toad.widgets.agent_response import AgentResponse

    class OwnedParagraph(PreparedParagraph):
        def _token_to_content(self, token):
            return Content(f"{self._markdown.id}: {token.content}")

    class OwnedMarkdown(AgentResponse):
        BLOCKS = {**PreparedConversationMarkdown.BLOCKS, "paragraph_open": OwnedParagraph}

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
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            document = OwnedMarkdown("Original source", paginate=False)
            document.id = "original-document"
            await app.selected_session.conversation.post(document)
            await document.update("Original source")
            paragraph = document.query_one(OwnedParagraph)
            await asyncio.wait_for(paragraph.wait_ready(), 20)
            assert paragraph._content.plain == "original-document: Original source"
            assert paragraph.prepared_content.original_text == paragraph._content.plain
            await document.update("Changed source")
            paragraph = document.query_one(OwnedParagraph)
            await asyncio.wait_for(paragraph.wait_ready(), 20)
            assert paragraph._content.plain == "original-document: Changed source"
            assert paragraph.prepared_content.original_text == paragraph._content.plain
            assert app._exception is None
        print("Real native App preserved custom bound converter across source replacement", flush=True)

    asyncio.run(mounted())
