"""Native clipboard keeps the complete selection across IRC and Markdown blocks."""

import asyncio
import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import Message, MessageType
from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.irc_message import IRCMessage, IRCMessageText


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-clipboard-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(125, 65)) as pilot:
            await pilot.pause()
            app.settings.set("ui.auto_copy", True)
            clipboard = ""
            terminal_writes = []
            truncate_terminal = True

            def native_copy(text):
                nonlocal clipboard
                clipboard = text

            def terminal_write(sequence):
                nonlocal clipboard
                if sequence.startswith("\x1b]52;c;"):
                    terminal_writes.append(sequence)
                    text = base64.b64decode(sequence[7:-1]).decode()
                    clipboard = text[:379] if truncate_terminal else text

            with patch("pyperclip.copy", side_effect=native_copy) as native, patch.object(
                app._driver, "write", side_effect=terminal_write
            ):
                view = app.screen.conversation
                await view.contents.remove_children()
                bodies = [
                    "TRACE-START\n" + "  File /project/module.py: repeated traceback content\n" * 10 + "TRACE-END",
                    "MIDDLE-MESSAGE " + "wrapped coordination text 界 café " * 12,
                    "LAST-MESSAGE " + "wrapped last paragraph " * 15 + "\nCOPY-END",
                ]
                rows = [await view.post(IRCMessage(Message("sender", "#comms", body, MessageType.INFO))) for body in bodies]
                await pilot.pause()
                first = rows[0].query_one(IRCMessageText)
                last = rows[-1].query_one(IRCMessageText)
                await pilot.mouse_down(first, offset=(0, 0))
                await pilot.mouse_up(last, offset=(len("COPY-END"), last.size.height - 1))
                await pilot.pause()
                selected = app.screen.get_selected_text()
                assert selected and len(selected) > 1000
                assert all(body in selected for body in bodies), selected
                assert selected.endswith("COPY-END"), selected
                assert clipboard == selected, (len(clipboard), len(selected))
                assert app.clipboard == selected
                assert not terminal_writes, "Successful native copy must not be overwritten through OSC 52"

                # Same real drag/auto-copy path through regular thread Markdown.
                app.screen.clear_selection()
                await view.contents.remove_children()
                paragraphs = [(f"REGULAR-{i} " + "ordinary threaded text café 界 " * 12).rstrip() for i in range(3)]
                paragraphs.append("REGULAR-COPY-END")
                response = await view.post(AgentResponse("\n\n".join(paragraphs), paginate=False))
                await pilot.pause()
                blocks = list(response.query("MarkdownParagraph"))
                await pilot.mouse_down(blocks[0], offset=(0, 0))
                await pilot.mouse_up(blocks[-1], offset=(len("REGULAR-COPY-END"), 0))
                await pilot.pause()
                selected = app.screen.get_selected_text()
                assert selected and all(paragraph in selected for paragraph in paragraphs), selected
                assert clipboard == selected and app.clipboard == selected
                assert not terminal_writes
                # Reverse-direction dragging must extract the same range.
                app.screen.clear_selection()
                await pilot.mouse_down(blocks[-1], offset=(len("REGULAR-COPY-END"), 0))
                await pilot.mouse_up(blocks[0], offset=(0, 0))
                await pilot.pause()
                assert app.screen.get_selected_text() == selected
                assert clipboard == selected and app.clipboard == selected
                app.copy_to_clipboard(selected * 100)
                assert clipboard == app.clipboard == selected * 100
                assert not terminal_writes

                # A failed/unavailable native clipboard still uses the terminal
                # transport and keeps Textual's internal clipboard up to date.
                truncate_terminal = False
                native.side_effect = RuntimeError("No native clipboard")
                app.copy_to_clipboard("fallback café 界")
                assert clipboard == app.clipboard == "fallback café 界"
                assert len(terminal_writes) == 1
                app._supports_pyperclip = False
                app.copy_to_clipboard("fallback without pyperclip")
                assert clipboard == app.clipboard == "fallback without pyperclip"
                assert len(terminal_writes) == 2
    print("clipboard: complete multi-message IRC and Markdown drag selections; terminal fallback only when needed")


if __name__ == "__main__":
    asyncio.run(main())
