"""Existing chat file references resolve to highlighted in-terminal previews."""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Markdown
from textual.widgets._markdown import MarkdownParagraph

from agent_comms import Thread, wire
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
        wire(root / "wire").register(Thread("project", frozenset(), str(project), pid=os.getpid()))
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            source = (
                "See plans/tag-channel-view-plan.md: and `plans/tag-channel-view-plan.md` "
                "but not plans/missing.md or https://example.com/plans/tag-channel-view-plan.md."
            )
            response = await app.screen.conversation.post(AgentResponse(source))
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
            owner_mode = app.current_mode
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
            assert app.current_mode == owner_mode

            # Even a pre-existing explicit Markdown file URI is previewed in
            # Toad rather than handed to the external browser.
            response.post_message(Markdown.LinkClicked(response, path.as_uri()))
            await pilot.pause()
            assert app.screen.query_one(FilePreview).path == path
            await app.close_session_mode(app.current_mode)
            assert app.current_mode == owner_mode

            response.post_message(Markdown.LinkClicked(response, links[0]))
            await pilot.pause()
            assert isinstance(app.screen, FilePreviewScreen)
            first_mode = app.current_mode
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
            assert await app.open_file_preview(path) == first_mode
            assert app.screen.query_one(FilePreview) is preview, "Opening a file twice duplicated its view"
            assert [tab.mode_name for tab in app.open_tabs].count(first_mode) == 1

            # Closing an inactive preview leaves the selected file and agent
            # intact; closing the selected preview returns to the last valid tab.
            other = project / "other.py"
            other.write_text("answer = 42\n")
            second_mode = await app.open_file_preview(other)
            await preview_ready(app, pilot)
            assert second_mode != first_mode and app.current_mode == second_mode
            assert [tab.mode_name for tab in app.open_tabs][:3] == [
                owner_mode, first_mode, second_mode]
            python_frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "answer = 42" in python_frame, "Python lexer did not render its source"
            assert await pilot.click(f"#close-{first_mode}")
            await pilot.pause()
            assert app.current_mode == second_mode and first_mode not in {
                tab.mode_name for tab in app.open_tabs}
            assert await pilot.click(f"#close-{second_mode}")
            await pilot.pause()
            assert app.current_mode == owner_mode
            assert owner.conversation.prompt.text == "Keep this draft"
            assert not owner.query(FilePreview)

            # Multiple open file tabs retain their own scroll/content. Back is
            # navigation; Close removes only the selected preview mode.
            first_mode = await app.open_file_preview(path)
            first_preview = app.screen.query_one(FilePreview)
            second_mode = await app.open_file_preview(other)
            assert [tab.mode_name for tab in app.open_tabs][:3] == [
                owner_mode, first_mode, second_mode]
            await app.screen.action_back()
            assert app.current_mode == first_mode
            assert app.screen.query_one(FilePreview) is first_preview
            assert second_mode in {tab.mode_name for tab in app.open_tabs}
            await app.switch_mode(second_mode)
            await app.close_session_mode(second_mode)
            assert app.current_mode == first_mode
            await app.close_session_mode(first_mode)
            assert app.current_mode == owner_mode
            assert owner.conversation.prompt.text == "Keep this draft"

            large_python = project / "preview.py"
            large_python.write_text("# UTF-8: café\n\n" + "def check(value: int) -> int:\n    return value + 1\n\n" * 2400)
            large_mode = await app.open_file_preview(large_python)
            await preview_ready(app, pilot)
            large_frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "def check(value: int) -> int:" in large_frame, "Large .py preview failed"
            assert app.current_mode == large_mode and app._exception is None
            await app.close_session_mode(large_mode)
            assert app.current_mode == owner_mode

            oversized = project / "oversized-preview.py"
            oversized.write_text("# FIRST-LINE-MARKER\nanswer = 42\n" + "pass\n" * 230_000)
            oversized_mode = await app.open_file_preview(oversized)
            await preview_ready(app, pilot)
            oversized_frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "exceeds 1 MiB; showing only the first 64 KiB" in oversized_frame
            assert "FIRST-LINE-MARKER" in oversized_frame
            assert app.current_mode == oversized_mode and app._exception is None
            await app.close_session_mode(oversized_mode)
            assert app.current_mode == owner_mode

            log_path = project / "session.log"
            log_path.write_text("LOG-PREVIEW-WORKS\n")
            log_mode = await app.open_file_preview(log_path)
            await preview_ready(app, pilot)
            log_frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "LOG-PREVIEW-WORKS" in log_frame and app._exception is None
            await app.close_session_mode(log_mode)
            assert app.current_mode == owner_mode

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
            assert app.current_mode == owner_mode
            nested_response.post_message(Markdown.LinkClicked(nested_response, basename_links[0]))
            await pilot.pause()
            assert app.screen.query_one(FilePreview).path == nested
            await app.close_session_mode(app.current_mode)
            assert app.current_mode == owner_mode
            duplicate = project / "other" / "declarations.py"
            duplicate.parent.mkdir()
            duplicate.write_text("# ANOTHER DECLARATION\n")
            with patch.object(app, "notify") as notices:
                nested_response.post_message(Markdown.LinkClicked(nested_response, basename_links[0]))
                await pilot.pause()
                assert app.current_mode == owner_mode
                assert "Several files named declarations.py" in notices.call_args.args[0]

            # A file link inside a channel should open directly above that
            # channel; closing it returns there, not through its owning agent.
            channel = await app.open_comms_session(
                owner_mode=owner_mode, project_path=project,
                me="project", target="#all", kind="channel",
            )
            chat = app.screen.query_one(CommsChatView)
            channel_response = AgentResponse("See plans/tag-channel-view-plan.md")
            await chat.contents.mount(channel_response)
            await pilot.pause()
            channel_response.post_message(Markdown.LinkClicked(channel_response, links[0]))
            await pilot.pause()
            assert isinstance(app.screen, FilePreviewScreen)
            assert app.screen.query_one(FilePreview).path == path
            assert [tab.mode_name for tab in app.open_tabs] == [
                owner_mode, channel, app.current_mode]
            await app.close_session_mode(app.current_mode)
            assert app.current_mode == channel
            assert owner.conversation.prompt.text == "Keep this draft"
    print("file paths: relative resolution, highlighting, exact source, and terminal preview passed")


if __name__ == "__main__":
    asyncio.run(main())
