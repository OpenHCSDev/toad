"""Existing chat file references resolve to highlighted in-terminal previews."""
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Markdown
from textual.widgets._markdown import MarkdownParagraph

from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from agent_comms.comms import wire
from toad.app import ToadApp
from toad.screens.file_preview import FilePreviewScreen
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.project_panel import FilePreview
from toad.widgets.session_tabs import SessionLabel, SessionTabClose


async def preview_ready(app, pilot):
    await asyncio.wait_for(app.screen.query_one(FilePreview).wait_ready(), 20)
    await pilot.pause()


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-file-links-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        project = root / "project"
        path = project / "plans" / "tag-channel-view-plan.md"
        path.parent.mkdir(parents=True)
        path.write_text("# Previewed plan\n\nResolved from chat.")
        wire(root / "wire").registry.declare(Thread("project", frozenset(), str(project), process_identity=ProcessIdentity.capture(os.getpid())))
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            source = (
                "See plans/tag-channel-view-plan.md: and `plans/tag-channel-view-plan.md` "
                "but not plans/missing.md or https://example.com/plans/tag-channel-view-plan.md."
            )
            response = await app.selected_session.conversation.post(AgentResponse(source))
            await pilot.pause()
            tokens = response._make_parser().parse(source)
            links = [
                child.attrs["href"]
                for token in tokens if token.type == "inline" and token.children
                for child in token.children
                if child.type == "link_open" and str(child.attrs["href"]).startswith("toad-file:")
            ]
            assert len(links) == 2
            assert all(link == f"toad-file:{path}" for link in links)
            assert response.source == source
            explicit = (f"[Absolute]({path}) [Relative](plans/tag-channel-view-plan.md) "
                        "[Website](https://example.com/preview.py) "
                        "[Missing](missing.py)")
            explicit_links = [
                child.attrs["href"]
                for token in response._make_parser().parse(explicit)
                if token.type == "inline" and token.children
                for child in token.children if child.type == "link_open"
            ]
            assert explicit_links == [
                f"toad-file:{path}", f"toad-file:{path}",
                "https://example.com/preview.py", "toad-file-search:missing.py",
            ], explicit_links
            owner_mode = app.selected_mode
            owner = app.screen
            owner.conversation.prompt.text = "Keep this draft"

            paragraph = next(part for part in response.query(MarkdownParagraph)
                             if "plans/tag-channel-view-plan.md" in str(part.render()))
            paragraph.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(paragraph, offset=(10, 0), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu), "Right-click did not open link menu"
            with patch.object(app, "copy_to_clipboard") as copied:
                copy = next(item for item in app.screen.query(ContextMenuItem)
                            if item.action == "copy_path")
                assert await pilot.click(copy)
                await pilot.pause()
                copied.assert_called_once_with(str(path.resolve()))
            assert app.selected_mode == owner_mode

            # Even a pre-existing explicit Markdown file URI is previewed in
            # Toad rather than handed to the external browser.
            response.post_message(Markdown.LinkClicked(response, path.as_uri()))
            await pilot.pause()
            assert app.screen.query_one(FilePreview).path == path
            await app.session_navigation.close(app.selected_mode)
            assert app.selected_mode == owner_mode

            response.post_message(Markdown.LinkClicked(response, links[0]))
            await pilot.pause()
            assert isinstance(app.screen, FilePreviewScreen)
            first_mode = app.selected_mode
            assert [tab.mode_name for tab in app.open_tabs][:2] == [owner_mode, first_mode]
            preview = app.screen.query_one(FilePreview)
            await preview_ready(app, pilot)
            assert preview.path == path.resolve()
            assert str(path.resolve()) in preview.query_one(".file-preview-path").render().plain
            assert "Previewed plan" in preview.query_one(Markdown).source
            assert app.screen.query_one(f"SessionLabel#{first_mode}").render().plain == path.name
            assert app.screen.query_one(f"#close-{first_mode}", SessionTabClose)
            assert app.session_tracker.session_count == 1
            assert owner.conversation.prompt.text == "Keep this draft"
            assert await app.session_navigation.preview(path) == first_mode
            assert app.screen.query_one(FilePreview) is preview, "Opening a file twice duplicated its view"
            assert [tab.mode_name for tab in app.open_tabs].count(first_mode) == 1

            # Closing an inactive preview leaves the selected file and agent
            # intact; closing the selected preview returns to the last valid tab.
            other = project / "other.py"
            other.write_text("answer = 42\n")
            second_mode = await app.session_navigation.preview(other)
            await preview_ready(app, pilot)
            assert second_mode != first_mode and app.selected_mode == second_mode
            assert [tab.mode_name for tab in app.open_tabs][:3] == [
                owner_mode, first_mode, second_mode]
            python_frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "answer = 42" in python_frame, "Python lexer did not render its source"
            assert await pilot.click(f"#close-{first_mode}")
            await pilot.pause()
            assert app.selected_mode == second_mode and first_mode not in {
                tab.mode_name for tab in app.open_tabs}
            assert await pilot.click(f"#close-{second_mode}")
            await pilot.pause()
            assert app.selected_mode == owner_mode
            assert owner.conversation.prompt.text == "Keep this draft"
            assert not owner.query(FilePreview)

            # Multiple open file tabs retain their own scroll/content. Back is
            # navigation; Close removes only the selected preview mode.
            first_mode = await app.session_navigation.preview(path)
            first_preview = app.screen.query_one(FilePreview)
            second_mode = await app.session_navigation.preview(other)
            assert [tab.mode_name for tab in app.open_tabs][:3] == [
                owner_mode, first_mode, second_mode]
            await app.screen.action_back()
            assert app.selected_mode == first_mode
            assert app.screen.query_one(FilePreview) is first_preview
            assert second_mode in {tab.mode_name for tab in app.open_tabs}
            await app.switch_mode(second_mode)
            await app.session_navigation.close(second_mode)
            assert app.selected_mode == first_mode
            await app.session_navigation.close(first_mode)
            assert app.selected_mode == owner_mode
            assert owner.conversation.prompt.text == "Keep this draft"

            large_python = project / "preview.py"
            large_python.write_text("# UTF-8: café\n\n" + "def check(value: int) -> int:\n    return value + 1\n\n" * 2400)
            large_mode = await app.session_navigation.preview(large_python)
            await preview_ready(app, pilot)
            large_frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "def check(value: int) -> int:" in large_frame, "Large .py preview failed"
            assert app.selected_mode == large_mode and app._exception is None
            await app.session_navigation.close(large_mode)
            assert app.selected_mode == owner_mode

            oversized = project / "oversized-preview.py"
            oversized.write_text("# FIRST-LINE-MARKER\nanswer = 42\n" + "pass\n" * 230_000)
            oversized_mode = await app.session_navigation.preview(oversized)
            await preview_ready(app, pilot)
            oversized_frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "exceeds 1 MiB; showing only the first 64 KiB" in oversized_frame, oversized_frame
            assert "FIRST-LINE-MARKER" in oversized_frame
            assert app.selected_mode == oversized_mode and app._exception is None
            await app.session_navigation.close(oversized_mode)
            assert app.selected_mode == owner_mode

            log_path = project / "session.log"
            log_path.write_text("LOG-PREVIEW-WORKS\n")
            log_mode = await app.session_navigation.preview(log_path)
            await preview_ready(app, pilot)
            log_frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "LOG-PREVIEW-WORKS" in log_frame and app._exception is None
            await app.session_navigation.close(log_mode)
            assert app.selected_mode == owner_mode

            # A bare filename in an agent response need not pretend to live
            # at the project root. Resolve it on activation only when unique.
            nested = project / "src" / "agent_comms" / "declarations.py"
            nested.parent.mkdir(parents=True)
            nested.write_text("# NESTED-DECLARATIONS-MARKER\n")
            nested_response = await owner.conversation.post(AgentResponse("See declarations.py"))
            await pilot.pause()
            basename_links = [
                child.attrs["href"]
                for token in nested_response._make_parser().parse("See declarations.py")
                if token.type == "inline" and token.children
                for child in token.children if child.type == "link_open"
            ]
            assert basename_links == ["toad-file-search:declarations.py"]
            absolute_link = f"[declarations.py]({nested})"
            absolute_links = [
                child.attrs["href"]
                for token in nested_response._make_parser().parse(absolute_link)
                if token.type == "inline" and token.children
                for child in token.children if child.type == "link_open"
            ]
            assert absolute_links == [f"toad-file:{nested}"]
            nested_paragraph = next(part for part in nested_response.query(MarkdownParagraph)
                                    if "declarations.py" in str(part.render()))
            nested_paragraph.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(nested_paragraph, offset=(7, 0), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            with patch.object(app, "copy_to_clipboard") as copied:
                copy = next(item for item in app.screen.query(ContextMenuItem)
                            if item.action == "copy_path")
                assert await pilot.click(copy)
                await pilot.pause()
                copied.assert_called_once_with(str(nested))
            assert app.selected_mode == owner_mode
            nested_response.post_message(Markdown.LinkClicked(nested_response, basename_links[0]))
            await pilot.pause()
            assert app.screen.query_one(FilePreview).path == nested
            await app.session_navigation.close(app.selected_mode)
            assert app.selected_mode == owner_mode
            duplicate = project / "other" / "declarations.py"
            duplicate.parent.mkdir()
            duplicate.write_text("# ANOTHER DECLARATION\n")
            with patch.object(app, "notify") as notices:
                nested_response.post_message(Markdown.LinkClicked(nested_response, basename_links[0]))
                await pilot.pause()
                assert app.selected_mode == owner_mode
                assert "Several files named declarations.py" in notices.call_args.args[0]

            # A file link inside a channel should open directly above that
            # channel; closing it returns there, not through its owning agent.
            channel = await channel_target("#all").open(NavigationContext(app, owner_mode, project, "project"))
            chat = app.screen.query_one(CommsChatView)
            channel_response = AgentResponse("See plans/tag-channel-view-plan.md")
            await chat.contents.mount(channel_response)
            await pilot.pause()
            channel_response.post_message(Markdown.LinkClicked(channel_response, links[0]))
            await pilot.pause()
            assert isinstance(app.screen, FilePreviewScreen)
            assert app.screen.query_one(FilePreview).path == path
            assert [tab.mode_name for tab in app.open_tabs] == [
                owner_mode, channel, app.selected_mode]
            await app.session_navigation.close(app.selected_mode)
            assert app.selected_mode == channel
            assert owner.conversation.prompt.text == "Keep this draft"
    print("file paths: relative resolution, highlighting, exact source, and terminal preview passed")


async def encoded_historical_journey(root: Path):
    """Actual installed Linux driver and clipboard; original saved-source selection."""
    import hashlib
    import importlib.metadata as metadata
    import json
    import subprocess
    import time
    from urllib.parse import quote
    from textual.actions import parse
    from textual.widgets import Select
    from toad.screens.historical_sessions import HistoricalSessions
    from toad.widgets.transcript_history import TranscriptHistory

    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    os.environ.update(AGENT_COMMS_ROOT=str(root / "live"),
                      XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                      XDG_DATA_HOME=str(root / "data"))
    activation = json.loads((Path(sys.prefix) / "activation.json").read_text())
    receipt = {"state": "running", "prefix": sys.prefix, "pins": activation["pins"],
               "checks": [], "provider_calls": 0, "public_mutations": 0}
    output = root / "receipt.json"
    native = activation["native_package"]
    spelling = "report space #50% literal%20.md"
    projects = [root / "old root #A%", root / "old root #B%"]
    old = wire(root / "old")
    script = """
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';
const {SessionManager}=await import(pathToFileURL(join(process.argv[1],'dist/core/session-manager.js')));
const manager=SessionManager.create(process.argv[2],join(process.argv[2],'sessions'));
manager.appendMessage({role:'user',content:'Saved request',timestamp:1});
manager.appendMessage({role:'assistant',content:[{type:'text',text:process.argv[3]}],
 provider:'fixture',model:'fixture',api:'fixture',stopReason:'stop',timestamp:2});
console.log(manager.getSessionFile());
"""
    paths = []
    for number, project in enumerate(projects):
        project.mkdir()
        path = project / "nested" / spelling
        path.parent.mkdir()
        path.write_text(f"# ORIGINAL-ROOT-{number}\nExact filename: {spelling}\n")
        paths.append(path)
        markdown = (f"[Encoded direct](<{quote(str(path))}>)\n\n"
                    f"[Deferred basename](<{quote(spelling)}>)\n\n"
                    "Autolink nested/plain.py\n")
        (path.parent / "plain.py").write_text("# Plain token producer\n")
        session = subprocess.check_output(["node", "--input-type=module", "-e", script,
                    native, str(project), markdown], text=True, timeout=10).strip()
        old.registry.declare(Thread(f"saved-{number}", frozenset({"team"}), str(project),
                                    session_file=session, created_at=10.0 + number))
    old.messaging.send_user_message("#source", "Saved source bus anchor outside tested conversations", worktree=str(root))
    live = wire(root / "live")
    live.views.attach_history(old.root)
    threads = tuple(t for t in live.views.historical_threads() if t.thread.name.startswith("saved-"))
    assert len(threads) == 2
    originals = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (root / "old").rglob("*") if p.is_file()}
    app = ToadApp(project_dir=str(root / "different live root"), mode="store")

    async def until(pilot, condition):
        async with asyncio.timeout(12):
            while not condition():
                await pilot.pause(.05)

    def frame(label):
        subprocess.run(["import", "-window", "root", str(root / (label + ".png"))],
                       check=True, timeout=5)
        (root / (label + ".svg")).write_text(app.export_screenshot())

    async def physical(pilot, x, y, button=1):
        # Cell coordinates come from the actual compositor, not guessed link text.
        window = subprocess.check_output(["xdotool", "search", "--class", "st"], text=True).splitlines()[-1]
        geometry = subprocess.check_output(["xdotool", "getwindowgeometry", "--shell", window],text=True)
        dims = dict(line.split("=",1) for line in geometry.splitlines() if "=" in line)
        width,height = int(dims["WIDTH"]),int(dims["HEIGHT"])
        px = 2 + int((x+.5)*(width-4)/app.size.width)
        py = 2 + int((y+.5)*(height-4)/app.size.height)
        subprocess.run(["xdotool", "mousemove", "--window", window, str(px), str(py), "click", str(button)],check=True)
        await pilot.pause(.25)

    def link_cell(href):
        for y in range(app.size.height):
            for x in range(app.size.width):
                action = app.screen.get_style_at(x,y).meta.get("@click")
                if isinstance(action,str):
                    try:
                        namespace,name,args = parse(action)
                    except Exception:
                        continue
                    if name == "link" and args == (href,):
                        return x,y
        raise AssertionError(f"Link not physically rendered: {href}")

    observed = []
    def observe(message):
        from textual import events
        from textual.worker import Worker
        if isinstance(message, (events.Click, Markdown.LinkClicked, Worker.StateChanged)):
            row = {"message":type(message).__qualname__, "repr":repr(message)}
            if isinstance(message,Markdown.LinkClicked):
                from toad.project_path_owner import ProjectPathOwner
                owner=ProjectPathOwner.containing(message.markdown)
                row.update(href=message.href,root=str(owner.project_root),
                           admitted=owner.admits_link(message.markdown,owner.project_root.resolve()))
            observed.append(row)
    try:
        async with app.run_test(headless=False, size=None, message_hook=observe) as pilot:
            await pilot.pause(.2)
            for number,path in enumerate(paths):
                history = HistoricalSessions(live, threads, name=f"saved-{number}")
                await app.push_screen(history)
                await until(pilot,lambda: bool(history.query(AgentResponse)))
                await pilot.pause(.3)
                assert history.project_root == projects[number]
                response = history.query_one(AgentResponse)
                tokens = response._make_parser().parse(response.source)
                hrefs = [c.attrs["href"] for t in tokens if t.type == "inline" and t.children
                         for c in t.children if c.type == "link_open"]
                direct = "toad-file:" + quote(str(path))
                deferred = "toad-file-search:" + quote(spelling)
                assert hrefs == [direct, deferred, "toad-file:" + quote(str(path.parent / "plain.py"))], hrefs
                frame(f"root-{number}-links")
                for kind,href in (("direct",direct),("deferred",deferred)):
                    await physical(pilot,*link_cell(href),button=3)
                    await until(pilot,lambda:isinstance(app.screen,ContextMenu))
                    item = next(i for i in app.screen.query(ContextMenuItem) if i.action == "copy_path")
                    await physical(pilot,item.region.x+2,item.region.y)
                    await until(pilot,lambda:not isinstance(app.screen,ContextMenu))
                    copied = subprocess.check_output(["xclip","-selection","clipboard","-o"],text=True,timeout=5)
                    assert copied == str(path),repr(copied)
                    receipt["checks"].append(f"root-{number}-{kind}-native-clipboard-exact")
                await physical(pilot,*link_cell(direct))
                await until(pilot,lambda:any(isinstance(v,FilePreviewScreen) for v in app.workspace_sessions.views.values()))
                # The historical modal may still cover the workspace; close only via its binding.
                if app.screen is history:
                    await pilot.press("escape")
                preview = app.selected_session.query_one(FilePreview)
                await asyncio.wait_for(preview.wait_ready(),12)
                assert preview.path == path
                await pilot.pause(.3)
                frame(f"root-{number}-preview")
                assert f"ORIGINAL-ROOT-{number}" in preview.query_one(Markdown).source
                receipt["checks"].append(f"root-{number}-actual-leftclick-preview")
                await app.session_navigation.close(app.selected_mode)
            assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest for name,digest in originals.items())
            receipt["originals_unchanged"] = True
            receipt["driver"] = type(app._driver).__name__
            assert receipt["driver"] == "LinuxDriver"
            assert app._exception is None
        receipt["state"] = "passed"
    except BaseException as error:
        receipt["state"] = "failed"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["elapsed_seconds"] = time.monotonic()-started
        receipt["sdk"] = metadata.version("agent-client-protocol")
        (root / "events.json").write_text(json.dumps(observed,indent=2)+"\n")
        output.write_text(json.dumps(receipt,indent=2)+"\n")


if __name__ == "__main__":
    import sys
    try:
        asyncio.run(encoded_historical_journey(Path(sys.argv[2])) if sys.argv[1:2] == ["--installed-owner"] else main())
    except BaseException:
        if sys.argv[1:2] == ["--installed-owner"]:
            import traceback
            (Path(sys.argv[2]) / "terminal-error.txt").write_text(traceback.format_exc())
        raise
