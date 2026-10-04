"""Streaming plain/ANSI tool output keeps its widget and exact copy semantics."""

import asyncio
import os
import json
from time import monotonic
from pathlib import Path
import tempfile

from rich.text import Text
from runtime_fixture import ToadApp, private_native_wire
from agent_comms.threads import Thread
from acp import schema as protocol
from toad.acp.status import ToolCallStatus
from toad.widgets.comms_chat import session_thread_name
from textual.content import Content
from textual import events
from textual.geometry import Offset, Size
from textual.screen import ModalScreen
from textual.widgets import Static
from textual.selection import SELECT_ALL, Selection
from toad.widgets.tool_call import ToolCall, ToolContent
from toad.widgets.viewport_body import MaterializingBody, RenderedBody
from toad.widgets.committed_presentation import protected_blocks
from toad.widgets.tool_content import MarkdownContent, TextContent
from toad.widgets.worker_static import WorkerStatic


def payload(text, *, kind="execute", raw_input=None):
    return ToolCallStatus.from_acp(protocol.ToolCall.model_validate({"toolCallId": "stream", "title": "Synthetic output", "kind": kind,
            "status": "in_progress", "rawInput": raw_input or {},
            "content": [{"type": "content", "content": {"type": "text", "text": text}}]}, strict=True))


class PublicationApp(ToadApp):
    """Observe the original display boundary; do not render/export another scene."""

    def __init__(self, **kwargs):
        self.observed_body = None
        self.displays = []
        self.checks = []
        super().__init__(**kwargs)

    def _display(self, screen, renderable):
        body = self.observed_body
        if renderable is not None and body is not None:
            visible = body in body.screen._compositor.visible_widgets
            assert not visible or body.body_ready, "unready registered body reached native display"
            self.displays.append({"time": monotonic(), "screen": type(screen).__name__,
                                  "body_visible": visible, "body_ready": body.body_ready})
        super()._display(screen, renderable)


class PendingUnmount(Static):
    """Hold an actual native child's Unmount, not a substituted removal answer."""

    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        super().__init__("retained native child", markup=False)

    async def on_unmount(self):
        self.entered.set()
        await self.release.wait()


class PublicationModal(ModalScreen):
    def compose(self):
        yield Static("Translucent modal over original workspace")


async def publication_lifetime(app, pilot, tool):
    conversation = app.selected_session.conversation
    window = conversation.window
    body = tool.query_one(ToolContent)
    await tool.update_tool_call(payload("gesture source"))
    tool.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    text = body.query_one(TextContent)
    assert await pilot.mouse_down(text, offset=(1, 0))
    intent = app.screen._select_state
    assert intent is not None and intent.end is None and not app.screen.selections
    assert text in set(app.screen._interaction_widgets())
    assert body in window.document_viewport.protected()
    assert tool in protected_blocks(conversation, (tool,))
    measured = await body.capture_native_paint(body._body_measurement)
    assert not isinstance(measured, RenderedBody)
    await tool.update_tool_call(payload("gesture replacement"))
    assert body.query_one(TextContent) is not text
    assert app.screen._select_state is None and text not in app.screen.selections
    await pilot.mouse_up()
    app.checks.append("pending MouseDown protects capture, viewport and committed row; replacement retires intent")

    await body.recompose()
    assert body.query_one(TextContent).render().plain == "gesture replacement"
    app.checks.append("direct ToolContent recompose preserves decoded source")
    await pilot.pause()
    held = PendingUnmount()
    await body.mount(held)
    tool.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert body.measured_rows > 0 and body.body_ready
    app.observed_body = body
    first = tool.update_tool_call(payload("# Intermediate writer\n\nOriginal native Markdown"))
    try:
        async with asyncio.timeout(5):
            await held.entered.wait()
        assert isinstance(body._body_measurement, MaterializingBody)
        assert isinstance(body._body_measurement.previous, RenderedBody)
        assert body.body_ready and app._batch_count == 0
        assert held not in body.screen._compositor.full_map
        assert held not in body.screen._compositor.visible_widgets
        assert held not in set(body.screen._interaction_widgets())
        second = tool.update_tool_call(payload("latest writer wins"))
        assert not first.is_done and not second.is_done
        editor = conversation.prompt.prompt_text_area
        app.screen.set_focus(editor, scroll_visible=False)
        await app._press_keys("body-pump")
        pumped = asyncio.Event()
        conversation.call_later(pumped.set)
        async with asyncio.timeout(5):
            await pumped.wait()
        assert "body-pump" in editor.text
        app.checks.append("captured pending native Unmount retires scene early and leaves Conversation input pump available")

        modal = PublicationModal()
        await app.push_screen(modal)
        await modal._mounted_event.wait()
        # Genuine source mutation retires captured paint while both writers wait.
        body.styles.color = "yellow"
        size = Size(112, 36)
        app._driver._size = size
        app.post_message(events.Resize(size, size))
        pumped = asyncio.Event()
        modal.call_later(pumped.set)
        async with asyncio.timeout(5):
            await pumped.wait()
        assert not body.body_ready and body in body.screen._compositor.visible_widgets
        before = len(app.displays)
        # The real terminal-admission method owns refusal before damage/render.
        modal._compositor_refresh()
        assert len(app.displays) == before and modal._repaint_required
        assert not body.screen._prepare_compositor_refresh()
        app.checks.append("translucent modal refuses width/style-invalidated captured body before native display/damage")
    finally:
        held.release.set()
    await first
    await second
    await app.pop_screen()
    await pilot.pause()
    assert body.body_ready and body.query_one(TextContent).render().plain == "latest writer wins"
    assert not body.query(MarkdownContent)
    assert "body-pump" in editor.text
    app.checks.append("original chained writers join before latest commit; modal return and editor draft preserved")
    tool.set_expanded(False)
    await tool.output.sync()
    assert not body.children
    tool.set_expanded(True)
    await tool.output.sync()
    await pilot.pause()
    assert body.query_one(TextContent).render().plain == "latest writer wins"
    app.checks.append("collapse and reentry consume same original part publication")
    app.observed_body = None


async def main():
    started = monotonic()
    with tempfile.TemporaryDirectory(prefix="toad-retained-tool-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = private_native_wire(root / "wire")
        comms.registry.declare(Thread(session_thread_name(root), frozenset(), str(root)))
        app = PublicationApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            await pilot.pause()
            tool = ToolCall(payload("first"))
            await app.selected_session.conversation.post(tool)
            tool.set_expanded(True)
            await tool.output.sync()
            await pilot.pause()
            original = tool.query_one(TextContent)
            values = ["[red]literal markup[/]\n界 é 🙂", "\x1b[31mred text\x1b[0m", "",
                      "\n".join(f"line {index}" for index in range(40)), "short"]
            for text in values:
                await tool.update_tool_call(payload(text))
                await pilot.pause()
                current = tool.query_one(TextContent)
                assert current is original
                expected = Content.from_rich_text(Text.from_ansi(text)) if "\x1b" in text else Content(text)
                assert current.render().plain == expected.plain
                assert current.render().spans == expected.spans
                assert current.get_selection(SELECT_ALL)[0] == expected.plain
                if text.startswith("line 0"):
                    assert current.size.height == 40
                elif text == "short":
                    assert current.size.height == 1

            long_text = "\n".join(f"line {index}" for index in range(40))
            await tool.update_tool_call(payload(long_text))
            app.screen.selections = {original: Selection(Offset(0, 30), Offset(4, 30))}
            await tool.update_tool_call(payload("tiny"))
            await pilot.pause()
            assert tool.query_one(TextContent) is not original
            assert not original.is_attached
            assert app.screen.get_selected_text() in (None, "")

            await tool.update_tool_call(payload("# Heading\n\nMarkdown body"))
            await pilot.pause()
            assert tool.query_one(MarkdownContent)
            await tool.update_tool_call(payload("plain again"))
            await pilot.pause()
            plain = tool.query_one(TextContent)
            assert not tool.query(MarkdownContent)

            code = "def example(value):\n    return value + 1\n"
            await tool.update_tool_call(payload(code, kind="read", raw_input={"path": "example.py"}))
            await pilot.pause()
            read = tool.query_one(WorkerStatic)
            await asyncio.wait_for(read.wait_ready(), 15)
            assert read._prepared is not None and any(line.text for line in read._prepared.lines)
            assert read.get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(code)
            # A filename change is an output change even when the raw text
            # dictionary is reused. ACP mutable input ends at the update boundary.
            same = payload(code, kind="read", raw_input={"path": "example.py"})
            await tool.update_tool_call(same)
            previous = tool.query_one(WorkerStatic)
            same.call.raw_input["path"] = "unrecognized.unknown"
            await tool.update_tool_call(same)
            changed = tool.query_one(WorkerStatic)
            assert changed is not previous and not previous.is_attached
            await asyncio.wait_for(changed.wait_ready(), 10)
            assert changed.get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(code)
            same.call.kind = "execute"
            await tool.update_tool_call(same)
            await pilot.pause()
            assert not tool.query(WorkerStatic)
            assert tool.query_one(TextContent).render().plain == code
            assert tool.query_one(TextContent).get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(code)
            await tool.update_tool_call(payload("literal [red]markup[/]", kind="read",
                                                raw_input={"path": "unrecognized.unknown"}))
            unknown = tool.query_one(WorkerStatic)
            await asyncio.wait_for(unknown.wait_ready(), 10)
            assert unknown.get_selection(SELECT_ALL)[0] == "literal [red]markup[/]"
            await tool.update_tool_call(payload("plain after read"))
            await pilot.pause()
            assert not tool.query(WorkerStatic) and tool.query_one(TextContent) is not plain
            await publication_lifetime(app, pilot, tool)
            assert app._exception is None
        assert app._exception is None
        output = Path(os.environ["TOOL_PUBLICATION_EVIDENCE"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "receipt.json").write_text(json.dumps({"completed": True, "elapsed": monotonic() - started, "checks": app.checks, "native_display_calls": app.displays, "providers": 0, "boundary": "Installed real App/native display admission, not physical terminal motion or CPU gain"}, indent=2) + "\n")
        await asyncio.get_running_loop().shutdown_default_executor()
    print("tool text: retained plain/ANSI widgets, literal markup, geometry, copy and selected/type-change fallbacks")


if __name__ == "__main__":
    asyncio.run(main())
