"""Installed Toad: actual selected log, clicked link, keyboard, resize and reopen."""

import asyncio
import json
import os
from pathlib import Path
import tempfile

import toad
from textual.widgets import Button, TextArea
from textual.widgets._markdown import MarkdownParagraph
from runtime_fixture import ToadApp
from toad.acp.log_records import LogPage
from toad.widgets.acp_log import AcpLogPreview
from toad.widgets.agent_response import AgentResponse
from toad.widgets.project_panel import FilePreview
from toad.widgets.worker_static import WorkerStatic


async def main():
    installed = Path(toad.__file__).parent
    assert "site-packages" in str(installed)
    ToadApp.CSS_PATH = [installed / "toad.tcss", installed / "screens/comms.tcss"]
    source = Path(os.environ["TOAD_LOG_UI_SOURCE"])
    snapshot = LogPage.read(source, FilePreview.MAX_BYTES)
    with tempfile.TemporaryDirectory(prefix="log-ui-") as directory:
        root = Path(directory)
        log = root / "state/toad/logs/observed-acp.txt"
        log.parent.mkdir(parents=True)
        log.write_bytes(snapshot.raw)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        os.environ.pop("TOAD_LOG", None)
        path_proof = []
        for reopen in range(2):
            app = ToadApp(project_dir=str(root))
            async with app.run_test(size=(100, 32)) as pilot:
                await pilot.pause()
                response = await app.screen.conversation.post(AgentResponse(f"[Open ACP log]({log})"))
                async with asyncio.timeout(10):
                    while not response.query(MarkdownParagraph):
                        await pilot.pause(0.02)
                paragraph = response.query_one(MarkdownParagraph)
                paragraph.scroll_visible(animate=False)
                await pilot.pause()
                assert await pilot.click(paragraph, offset=(5, 0))
                async with asyncio.timeout(10):
                    while not app.screen.query(AcpLogPreview):
                        await pilot.pause(0.02)
                view = app.screen.query_one(AcpLogPreview)
                await asyncio.wait_for(view.wait_ready(), 10)
                await pilot.pause()
                area = view.query_one(TextArea)
                assert "Unsettled owner input; compaction not dispatched" in area.text
                assert "The usage limit has been reached" in area.text
                assert area.soft_wrap and area.read_only
                assert await pilot.click("#log-events")
                await pilot.pause()
                assert "session/update" in area.text and "response" in area.text
                assert await pilot.click("#log-raw")
                await pilot.pause()
                assert area.text == log.read_bytes().decode("utf-8", errors="replace")
                assert await pilot.click("#log-wrap")
                await pilot.pause()
                assert not area.soft_wrap
                # Keyboard reaches the final column rather than clipping it.
                longest = max(range(len(area.document.lines)), key=lambda index: len(area.document.lines[index]))
                line = area.document.lines[longest]
                area.move_cursor((longest, 0))
                await pilot.press("end")
                await pilot.pause()
                assert area.cursor_location == (longest, len(line))
                assert area.scroll_x > 0 and area.horizontal_scrollbar.display
                await pilot.press("shift+home")
                await pilot.pause()
                assert area.selected_text == line
                # Resizing the real app retains controls and selectable source.
                await pilot.resize_terminal(50, 24)
                await pilot.pause()
                for selector in ["#log-errors", "#log-events", "#log-raw", "#log-wrap", "#log-earlier", "#log-latest"]:
                    button = view.query_one(selector)
                    assert button.region.right <= app.screen.size.width, (selector, button.region)
                assert await pilot.click("#log-wrap")
                await pilot.pause()
                assert area.soft_wrap
                assert await pilot.click("#log-errors")
                await pilot.pause()
                assert "Provider usage limit reached" in area.text
                assert area.region.height >= 5
                if reopen == 0:
                    # ANSI default colors have no terminal palette in SVG;
                    # use the installed app's ordinary explicit-color theme.
                    app.theme = "textual-dark"
                    await pilot.pause()
                    await pilot.resize_terminal(100, 32)
                    await pilot.pause()
                    app.save_screenshot(filename="errors-real-log.svg", path=str(Path(os.environ["TOAD_LOG_EVIDENCE"])))
                    with log.open("a") as stream:
                        stream.write("backend stderr: appended local diagnostic\n")
                    assert await pilot.click("#log-latest")
                    await pilot.pause()
                    await asyncio.wait_for(view.wait_ready(), 10)
                    await pilot.pause()
                    assert "appended local diagnostic" in area.text
                else:
                    # Exercise actual Earlier/Latest buttons on a real owned
                    # file beyond the shared bound, not a mocked page object.
                    padding = (
                        "[agent] " + json.dumps({"jsonrpc": "2.0", "id": 8, "result": "z" * 1024}) + "\n"
                    ).encode()
                    with log.open("ab") as stream:
                        stream.write(padding * (FilePreview.MAX_BYTES // len(padding) + 1))
                    assert await pilot.click("#log-latest")
                    await pilot.pause()
                    await asyncio.wait_for(view.wait_ready(), 10)
                    await pilot.pause()
                    assert view.page.start > 0 and len(view.page.raw) <= FilePreview.MAX_BYTES
                    assert await pilot.click("#log-earlier")
                    await pilot.pause()
                    await asyncio.wait_for(view.wait_ready(), 10)
                    await pilot.pause()
                    assert view.page.start == 0
                    assert "Unsettled owner input; compaction not dispatched" in area.text
                    # Real filesystem failure must be visible, and recovery
                    # must reread the file rather than retain stale records.
                    log.unlink()
                    assert await pilot.click("#log-latest")
                    await pilot.pause()
                    await asyncio.wait_for(view.wait_ready(), 10)
                    await pilot.pause()
                    assert "Unable to read log" in area.text
                    assert view.page is None and view.query_one("#log-earlier", Button).disabled
                    log.write_bytes(snapshot.raw)
                    # Textual ignores another click during its active effect;
                    # wait for the real control to accept the recovery click.
                    async with asyncio.timeout(3):
                        while view.query_one("#log-latest", Button).has_class("-active"):
                            await pilot.pause(0.02)
                    assert await pilot.click("#log-latest")
                    await pilot.pause()
                    await asyncio.wait_for(view.wait_ready(), 10)
                    await pilot.pause()
                    assert "The usage limit has been reached" in area.text
                assert app._exception is None
                path_proof.append(
                    {
                        "new_app": reopen,
                        "clicked_log_link": True,
                        "horizontal_keyboard": True,
                        "selection": True,
                        "resize": True,
                    }
                )
                area.focus()
                await pilot.press("ctrl+w")
                await pilot.pause()
                assert not app.screen.query(AcpLogPreview)
                if reopen == 1:
                    plain = root / "ordinary.txt"
                    plain.write_text("Project file: 界 café\n")
                    await app.open_file_preview(plain)
                    preview = app.screen.query_one(FilePreview)
                    await asyncio.wait_for(preview.wait_ready(), 10)
                    await pilot.pause()
                    code = preview.query_one(WorkerStatic)
                    painted = "\n".join(code.render_line(row).text for row in range(code.size.height))
                    assert "Project file: 界 café" in painted, painted[:800]
                    await pilot.press("ctrl+w")
                    await pilot.pause()
                    assert not app.screen.query(FilePreview)
        print(
            json.dumps(
                {
                    "boundary": "installed actual Toad with observed user ACP log; no mocks",
                    "source": str(source),
                    "source_bytes": snapshot.total,
                    "bounded_copy_bytes": len(snapshot.raw),
                    "apps": path_proof,
                    "toad_import": str(installed),
                    "paging_and_read_recovery": True,
                    "ordinary_project_preview": True,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
