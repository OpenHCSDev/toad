"""Installed block selection, menu keys, painted copy and private X11 transport."""
import asyncio
import os
from pathlib import Path
import select
import subprocess
import tempfile

from textual.widgets import Static
from toad.block_content import BlockContent
from toad.block_navigation import ConversationBlock
from toad.menus import MenuItem
from toad.widgets.agent_response import AgentResponse
from toad.widgets.menu import Menu
from toad.widgets.tool_call import ToolCall
from toad.widgets.user_input import UserInput
from runtime_fixture import ToadApp


class DeclaredExtraBlock(ConversationBlock, Static):
    def get_clipboard_text(self):
        return "DECLARED_COPY café 界"

    def get_block_menu(self):
        return (MenuItem("Apply declared action", "block.choose", "z"),)

    def action_choose(self):
        self.update("DECLARED_ACTION_PAINT")


def frame(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def until(pilot, condition):
    async with asyncio.timeout(5):
        while not condition():
            await pilot.pause(.02)


async def main():
    read_fd, write_fd = os.pipe()
    server = subprocess.Popen(
        ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1100x740x24", "-nolisten", "tcp"],
        pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    os.close(write_fd)
    try:
        assert select.select([read_fd], [], [], 5)[0], "Private X11 did not start"
        os.environ["DISPLAY"] = ":" + os.read(read_fd, 32).decode().strip()
        os.environ.pop("WAYLAND_DISPLAY", None)
        with tempfile.TemporaryDirectory(prefix="block-", dir="/var/tmp") as directory:
            root = Path(directory)
            os.environ.update(
                AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
                XDG_DATA_HOME=str(root/'data'), XDG_STATE_HOME=str(root/'state'),
            )
            app = ToadApp(project_dir=str(root))
            async with app.run_test(size=(110, 38)) as pilot:
                await pilot.pause()
                view = app.screen.conversation
                await view.contents.remove_children()
                user = UserInput("USER_COPY_PAINT")
                response = AgentResponse("PARAGRAPH_COPY_PAINT\n\n```python\nprint('FENCE_COPY_PAINT')\n```", paginate=False)
                extra = DeclaredExtraBlock("DECLARED_NEW_PAINT")
                tool = ToolCall({"toolCallId":"t4-expansion", "title":"Actual expansion", "kind":"other", "status":"in_progress",
                                 "content":[{"type":"content","content":{"type":"text","text":"TOOL_EXPANSION_PAINT"}}]})
                tool.set_expanded(False)
                await view.contents.mount(user, response, extra, tool)
                await until(pilot, lambda: len(response.displayed_children) >= 3)

                async def choose(widget, key):
                    assert isinstance(widget, BlockContent), type(widget)
                    assert view.navigation.select(widget)
                    view.refresh_block_cursor()
                    await pilot.press("enter")
                    await until(pilot, lambda: bool(view.query(Menu)))
                    assert "opy to clipboard" in frame(app), frame(app)
                    await pilot.press(key)
                    await until(pilot, lambda: not view.query(Menu))

                async def copied(widget, text):
                    await choose(widget, "c")
                    assert app.clipboard == text
                    actual = subprocess.run(["xclip","-selection","clipboard","-o"],
                                            capture_output=True, timeout=3, check=True)
                    assert actual.stdout.decode() == text

                await copied(user, "USER_COPY_PAINT")
                await choose(user, "p")
                assert view.prompt.text == "USER_COPY_PAINT"
                assert "USER_COPY_PAINT" in frame(app)
                view.prompt.text = ""

                paragraph, fence = response.displayed_children[-2:]
                await copied(paragraph, paragraph.source)
                await choose(paragraph, "p")
                assert view.prompt.text == paragraph.source
                view.prompt.text = ""
                await copied(fence, fence._content.plain)
                await choose(fence, "p")
                assert view.prompt.text == fence.source
                assert "FENCE_COPY_PAINT" in frame(app)
                view.prompt.text = ""
                # Decorative prefix selection remains a genuine empty capability.
                prior = app.clipboard
                await choose(response.displayed_children[0], "c")
                assert app.clipboard == prior and view.prompt.text == ""

                await copied(extra, "DECLARED_COPY café 界")
                await choose(extra, "z")
                assert "DECLARED_ACTION_PAINT" in frame(app)
                assert view.navigation.select(tool)
                view.refresh_block_cursor()
                assert view.check_action("expand_block", ()) is True
                assert view.check_action("collapse_block", ()) is False
                await pilot.press("space")
                await until(pilot, lambda: tool.expanded and "TOOL_EXPANSION_PAINT" in frame(app))
                assert view.check_action("expand_block", ()) is False
                assert view.check_action("collapse_block", ()) is True
                await pilot.press("space")
                await until(pilot, lambda: not tool.expanded)
                assert "TOOL_EXPANSION_PAINT" not in frame(app)
                await pilot.resize_terminal(83, 31)
                assert view.navigation.select(extra)
                view.refresh_block_cursor()
                await copied(extra, "DECLARED_COPY café 界")
                assert "DECLARED_ACTION_PAINT" in frame(app)
                assert view.check_action("expand_block", ()) is None
                assert view.check_action("collapse_block", ()) is False
                print("PASS installed mixed nominal blocks, actual menu keys/cropped paint, private X11 copy, prompt, resize, expansion and new-case action")
    finally:
        os.close(read_fd)
        server.terminate()
        server.wait(timeout=3)


if __name__ == '__main__':
    asyncio.run(main())
