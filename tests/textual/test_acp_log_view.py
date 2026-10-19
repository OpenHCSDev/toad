"""Textual-facing: the ACP log preview's text area, buttons, scrolling, resize and paging are Textual widgets
reading a physical log file; navigation opens it."""

import asyncio
import json

from textual.widgets import Button, TextArea

from toad.file_kind import FileKind
from toad.widgets.acp_log import AcpLogPreview
from toad.widgets.project_panel import FilePreview
from toad.widgets.worker_static import WorkerStatic

LONG = "word " * 90


def log_lines() -> str:
    updates = {"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s", "update": {
        "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hello " + LONG}}}}
    answer = {"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}}
    refused = {"jsonrpc": "2.0", "id": 2, "error": {"code": -32603, "message": "The usage limit has been reached"}}
    return (f"[client] {{'jsonrpc': '2.0', 'id': 1, 'method': 'session/prompt', 'params': {{'prompt': 'hi'}}}}\n"
            f"[agent] {json.dumps(updates)}\n"
            "backend stderr: Unsettled owner input; compaction not dispatched\n"
            f"[agent] {json.dumps(answer)}\n"
            f"[agent] {json.dumps(refused)}\n")


def write_log(workspace):
    log = workspace.roots.attempt / "state/toad/logs/ACP session café.txt"
    log.parent.mkdir(parents=True)
    log.write_text(log_lines())
    return log


async def open_log(ui, log):
    """Open the log preview as the project navigation does, and return it."""
    app, _pilot = ui.textual
    await app.session_navigation.preview(log)
    await ui.until(lambda: app.screen.query(AcpLogPreview), why="the log preview")
    view = app.screen.query_one(AcpLogPreview)
    await asyncio.wait_for(view.wait_ready(), 10)
    await ui.step()
    return view


async def reread(ui, view, button):
    _app, pilot = ui.textual
    assert await pilot.click(button)
    await ui.step()
    await asyncio.wait_for(view.wait_ready(), 10)
    await ui.step()


async def test_log_views_wrap_keyboard_resize_and_latest_read_the_physical_log(workspace):
    log = write_log(workspace)
    async with workspace.app(size=(100, 32)) as ui:
        app, pilot = ui.textual
        view = await open_log(ui, log)
        area = view.query_one(TextArea)
        assert "Unsettled owner input; compaction not dispatched" in area.text
        assert "The usage limit has been reached" in area.text
        assert area.soft_wrap and area.read_only
        assert await pilot.click("#log-events")
        await ui.step()
        assert "session/update" in area.text and "response" in area.text
        assert await pilot.click("#log-raw")
        await ui.step()
        assert area.text == log.read_bytes().decode("utf-8", errors="replace")
        assert await pilot.click("#log-wrap")
        await ui.step()
        assert not area.soft_wrap
        # Keyboard reaches the final column rather than clipping it.
        longest = max(range(len(area.document.lines)), key=lambda index: len(area.document.lines[index]))
        line = area.document.lines[longest]
        area.move_cursor((longest, 0))
        await ui.press("end")
        assert area.cursor_location == (longest, len(line))
        assert area.scroll_x > 0 and area.horizontal_scrollbar.display
        await ui.press("shift+home")
        assert area.selected_text == line
        # Resizing the real app retains controls and selectable source.
        await ui.resize(50, 24)
        for selector in ["#log-errors", "#log-events", "#log-raw", "#log-wrap", "#log-earlier", "#log-latest"]:
            button = view.query_one(selector)
            assert button.region.right <= app.screen.size.width, (selector, button.region)
        assert await pilot.click("#log-wrap")
        await ui.step()
        assert area.soft_wrap
        assert await pilot.click("#log-errors")
        await ui.step()
        assert "Provider usage limit reached" in area.text
        assert area.region.height >= 5
        with log.open("a") as stream:
            stream.write("backend stderr: appended local diagnostic\n")
        await reread(ui, view, "#log-latest")
        assert "appended local diagnostic" in area.text
        area.focus()
        await ui.press("ctrl+w")
        assert not app.screen.query(AcpLogPreview)
        assert ui.failure() is None


async def test_earlier_and_latest_page_through_a_log_larger_than_one_page_and_recover_from_a_missing_file(workspace):
    log = write_log(workspace)
    original = log.read_bytes()
    async with workspace.app(size=(100, 32)) as ui:
        app, pilot = ui.textual
        view = await open_log(ui, log)
        area = view.query_one(TextArea)
        # Actual Earlier/Latest buttons on a real file beyond the shared bound.
        padding = ("[agent] " + json.dumps({"jsonrpc": "2.0", "id": 8, "result": "z" * 1024}) + "\n").encode()
        with log.open("ab") as stream:
            stream.write(padding * (FileKind.MAX_BYTES // len(padding) + 1))
        await reread(ui, view, "#log-latest")
        assert view.page.start > 0 and len(view.page.raw) <= FileKind.MAX_BYTES
        await reread(ui, view, "#log-earlier")
        assert view.page.start == 0
        assert "Unsettled owner input; compaction not dispatched" in area.text
        # A real filesystem failure must be visible, and recovery must reread the file.
        log.unlink()
        await reread(ui, view, "#log-latest")
        assert "Unable to read log" in area.text
        assert view.page is None and view.query_one("#log-earlier", Button).disabled
        log.write_bytes(original)
        # Textual ignores another click during its active effect; wait for the control to accept it.
        await ui.until(lambda: not view.query_one("#log-latest", Button).has_class("-active"),
                       why="the Latest button to accept a click")
        await reread(ui, view, "#log-latest")
        assert "The usage limit has been reached" in area.text
        assert ui.failure() is None


async def test_a_full_raw_page_is_drawn_exactly_and_follows_new_lines_only_while_its_end_is_in_view(workspace):
    log = write_log(workspace)
    padding = ("[agent] " + json.dumps({"jsonrpc": "2.0", "id": 8, "result": "z" * 1024}) + "\n").encode()
    with log.open("ab") as stream:
        stream.write(padding * (FileKind.MAX_BYTES // len(padding) + 1))
    async with workspace.app(size=(100, 32)) as ui:
        view = await open_log(ui, log)
        area = view.query_one(TextArea)
        await reread(ui, view, "#log-raw")
        # The page enters the text area in slices; together they are the page.
        assert len(view.page.raw) > 100 * view.SLICE
        assert area.text == view.page.raw.decode("utf-8", errors="replace")
        await ui.until(lambda: area.max_scroll_y > 0 and area.scroll_y == area.max_scroll_y,
                       why="the newest line in view")
        with log.open("a") as stream:
            stream.write("backend stderr: written while the end is in view\n")
        await ui.until(lambda: area.text.endswith("written while the end is in view\n"),
                       why="the new line drawn without asking", seconds=10)
        await ui.until(lambda: area.scroll_y == area.max_scroll_y, why="the new line in view")
        # A reader who scrolled back is left where they are.
        area.scroll_home(animate=False)
        await ui.step()
        with log.open("a") as stream:
            stream.write("backend stderr: written while reading earlier lines\n")
        await ui.step(3 * view.FOLLOW_INTERVAL)
        assert "written while reading earlier lines" not in area.text and area.scroll_y == 0
        await reread(ui, view, "#log-latest")
        assert area.text.endswith("written while reading earlier lines\n")
        assert ui.failure() is None


async def test_an_ordinary_project_file_previews_with_wide_and_accented_text(workspace):
    plain = workspace.project / "ordinary.txt"
    plain.write_text("Project file: 界 café\n")
    async with workspace.app(size=(100, 32)) as ui:
        app, _pilot = ui.textual
        await app.session_navigation.preview(plain)
        preview = app.screen.query_one(FilePreview)
        await asyncio.wait_for(preview.wait_ready(), 10)
        await ui.step()
        code = preview.query_one(WorkerStatic)
        painted = "\n".join(code.render_line(row).text for row in range(code.size.height))
        assert "Project file: 界 café" in painted, painted[:800]
        await ui.press("ctrl+w")
        assert not app.screen.query(FilePreview)
