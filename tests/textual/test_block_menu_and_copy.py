"""Textual-facing: the block cursor, its menu keys, expansion and copy/paste-to-prompt work for each kind of conversation block, with the clipboard going through a private X11 display."""

import os
import base64
from pathlib import Path
import select
import subprocess

import pytest
from textual.widgets import Static

from toad.block_content import BlockContent
from toad.block_navigation import ConversationBlock
from toad.widgets.conversation import Conversation, FocusPromptAction
from textual.keys import KeyDeclaration
from textual.document._editing import EditingMode
from toad.menus import MenuItem
from toad.widgets.menu import Menu
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from toad.acp.status import ToolCallStatus
from acp.schema import ToolCall as SDKToolCall
from toad.prompt.extract import extract_paths_from_prompt
from toad.widgets.project_panel import FilePreview
from toad.project_link import DirectProjectFileLink


class DeclaredExtraBlock(ConversationBlock, Static):
    def get_clipboard_text(self):
        return "DECLARED_COPY café 界"

    def get_block_menu(self):
        return (MenuItem("Apply declared action", "block.choose", "z"),)

    def action_choose(self):
        self.update("DECLARED_ACTION_PAINT")


@pytest.fixture
def private_display(private_display_programs, monkeypatch):
    """A private X11 display for this test's clipboard; yields the xclip program."""
    xvfb, xclip = private_display_programs
    read_fd, write_fd = os.pipe()
    server = subprocess.Popen(
        [
            xvfb,
            "-displayfd",
            str(write_fd),
            "-screen",
            "0",
            "1100x740x24",
            "-nolisten",
            "tcp",
        ],
        pass_fds=(write_fd,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.close(write_fd)
    try:
        assert select.select([read_fd], [], [], 5)[0], "Private X11 did not start"
        monkeypatch.setenv("DISPLAY", ":" + os.read(read_fd, 32).decode().strip())
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        yield xclip
    finally:
        os.close(read_fd)
        server.terminate()
        server.wait(timeout=3)


async def test_clipboard_image_sends_to_channel_and_dm_and_opens_its_preview(
    workspace, private_display, monkeypatch,
):
    """Real X selection -> composer -> wire/inboxes -> image preview -> tab return."""
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg=="
    )
    source = workspace.project / "clipboard source.png"
    source.write_bytes(png)
    monkeypatch.setenv("XDG_DATA_HOME", str(workspace.roots.attempt / "data with spaces"))
    workspace.thread("alpha", "team")
    workspace.thread("beta", "team")
    subprocess.run(
        [private_display, "-selection", "clipboard", "-t", "image/png", str(source)],
        check=True, timeout=3,
    )
    comms = workspace.comms
    async with workspace.app(size=(160, 42)) as ui:
        app, _ = ui.textual

        async def send_and_preview(tab, target):
            await ui.write_draft("Look at this")
            await ui.press("ctrl+v")
            await ui.until(lambda: "clipboard-" in ui.draft(), why="the actual clipboard image attachment")
            body = ui.draft()
            path = Path(next(extract_paths_from_prompt(body))[0])
            assert path.read_bytes() == png
            assert path.stat().st_mode & 0o777 == 0o600
            await ui.press("enter")
            await ui.until(
                lambda: any(message.target == target and message.body == body
                            for message in comms.bus.inbox("beta").page.messages),
                why="the original image reference delivered to the recipient",
            )
            await ui.until_shows("clipboard-")
            expected = DirectProjectFileLink(path, original_root=workspace.project)
            await ui.until(lambda: ui.link_at("clipboard-") == expected.click,
                           why="the complete quoted attachment rendered as a file link")
            await ui.click("clipboard-")
            await ui.until(lambda: ui.selected_tab != tab, why="the image preview tab")
            preview = app.selected_session.query_one(FilePreview)
            await preview.wait_ready()
            assert preview.path == path and not preview.loading_label.display
            preview_tab = ui.selected_tab
            await ui.select_tab(tab)
            assert ui.draft() == ""
            await ui.close_tab(preview_tab)
            return body

        channel = await ui.open_channel("#team", actor="alpha")
        body = await send_and_preview(channel, "#team")
        assert any(message.body == body for message in comms.bus.inbox("alpha").page.messages)
        direct = await ui.open_direct("beta", actor="alpha")
        await send_and_preview(direct, "beta")


async def test_block_menu_copy_prompt_and_expansion(workspace, private_display):
    xclip = private_display
    async with workspace.app(size=(110, 38)) as ui:
        app, _ = ui.textual
        view = ui.conversation
        app.set_keymap({KeyDeclaration.binding_id_for(Conversation.action_select_block, EditingMode): "f9",
                        FocusPromptAction.binding_id(EditingMode): "f8"})
        history = view.transcript.binding.history
        await view.contents.remove_children(
            tuple(child for child in view.contents.children if child is not history)
        )
        user = UserInput("USER_COPY_PAINT")
        extra = DeclaredExtraBlock("DECLARED_NEW_PAINT")
        tool = ToolCall(
            ToolCallStatus.from_acp(
                SDKToolCall.model_validate(
                    {
                        "toolCallId": "t4-expansion",
                        "title": "Actual expansion",
                        "kind": "other",
                        "status": "in_progress",
                        "content": [
                            {
                                "type": "content",
                                "content": {
                                    "type": "text",
                                    "text": "TOOL_EXPANSION_PAINT",
                                },
                            }
                        ],
                    }
                )
            )
        )
        tool.set_expanded(False)
        await view.contents.mount(user, extra, tool)
        await ui.step()
        assert not view.navigation.accepts_menu_owner(extra)

        async def choose(widget, key):
            assert isinstance(widget, BlockContent), type(widget)
            assert view.navigation.select(widget)
            assert view.navigation.accepts_menu_owner(widget)
            view.refresh_block_cursor(lambda cursor: cursor.show_moved_to(view.window))
            await ui.press("enter")
            assert not view.query(Menu), "The remapped menu must not keep its default Enter key"
            await ui.press("f9")
            await ui.until(lambda: bool(view.query(Menu)), why="the block menu")
            assert "opy to clipboard" in ui.visible_text(), ui.visible_text()
            await ui.press(key)
            await ui.until(lambda: not view.query(Menu), why="the block menu to close")

        async def copied(widget, text):
            await choose(widget, "c")
            assert app.clipboard == text
            actual = subprocess.run(
                [xclip, "-selection", "clipboard", "-o"],
                capture_output=True,
                timeout=3,
                check=True,
            )
            assert actual.stdout.decode() == text

        await copied(user, "USER_COPY_PAINT")
        await choose(user, "p")
        assert ui.draft() == "USER_COPY_PAINT"
        assert ui.shows("USER_COPY_PAINT")
        await ui.write_draft("")

        await copied(extra, "DECLARED_COPY café 界")
        await choose(extra, "z")
        await ui.until_shows("DECLARED_ACTION_PAINT")
        assert view.navigation.select(tool)
        view.refresh_block_cursor(lambda cursor: cursor.show_moved_to(view.window))
        assert view.check_action("expand_block", ()) is True
        assert view.check_action("collapse_block", ()) is False
        await ui.press("space")
        await ui.until(
            lambda: tool.expanded and ui.shows("TOOL_EXPANSION_PAINT"),
            why="the tool call to expand",
        )
        assert view.check_action("expand_block", ()) is False
        assert view.check_action("collapse_block", ()) is True
        await ui.press("space")
        await ui.until(lambda: not tool.expanded, why="the tool call to collapse")
        assert not ui.shows("TOOL_EXPANSION_PAINT")
        await ui.resize(83, 31)
        assert view.navigation.select(extra)
        view.refresh_block_cursor(lambda cursor: cursor.show_moved_to(view.window))
        await copied(extra, "DECLARED_COPY café 界")
        assert ui.shows("DECLARED_ACTION_PAINT")
        assert view.check_action("expand_block", ()) is None
        assert view.check_action("collapse_block", ()) is False
        view.navigation.clear()
        view.refresh_block_cursor(lambda cursor: cursor.show_moved_to(view.window))
        await ui.step()
        assert view.navigation.cursor.selected_widgets == ()
        assert view.prompt.has_focus_within
        view.window.focus()
        await ui.press("end")
        assert not view.prompt.has_focus_within
        await ui.press("f8")
        assert view.prompt.has_focus_within
