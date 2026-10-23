"""Textual-facing: the block cursor, its menu keys, expansion and copy/paste-to-prompt work for each kind of conversation block, with the clipboard going through a private X11 display."""

import os
import select
import subprocess

import pytest
from textual.widgets import Static

from toad.block_content import BlockContent
from toad.block_navigation import ConversationBlock
from toad.menus import MenuItem
from toad.widgets.menu import Menu
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from toad.acp.status import ToolCallStatus
from acp.schema import ToolCall as SDKToolCall


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


async def test_block_menu_copy_prompt_and_expansion(workspace, private_display):
    xclip = private_display
    async with workspace.app(size=(110, 38)) as ui:
        app, _ = ui.textual
        view = ui.conversation
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
