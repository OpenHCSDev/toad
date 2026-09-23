"""Typing command-looking prose must never authorize shell execution."""

import asyncio
import os
import tempfile
from pathlib import Path

from toad.app import ToadApp
from toad.messages import UserInputSubmitted


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-prompt-routing-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prompt = app.screen.conversation.prompt
            area = prompt.prompt_text_area
            captured: list[UserInputSubmitted] = []
            original = area.post_message

            def capture(message):
                if isinstance(message, UserInputSubmitted):
                    captured.append(message)
                    return True
                return original(message)

            area.post_message = capture
            assert not prompt.prompt_text_area.placeholder
            for text in ("openhcs", "open the project", "git status", "python", "$100 budget", "@peer", "!literal"):
                prompt.focus()
                for char in text:
                    await pilot.press(char if char != " " else "space")
                    assert not prompt.shell_mode and not area.shell_mode, text
                await pilot.press("enter")
                await pilot.pause()
                assert captured[-1].body == text and not captured[-1].shell
            # Enter submits the whole prompt even after paste or Markdown makes
            # it multiline. Ctrl+J remains an explicit newline, never a send.
            for text in ("first line\nsecond line", "```python\nprint('hello')\n```"):
                prompt.text = text
                prompt.focus()
                await pilot.pause()
                count = len(captured)
                await pilot.press("enter")
                await pilot.pause()
                assert len(captured) == count + 1
                assert captured[-1].body == text and not captured[-1].shell
                assert not prompt.text
            prompt.text = "line one"
            prompt.focus()
            await pilot.pause()
            count = len(captured)
            await pilot.press("ctrl+j", *"line two", "ctrl+j", *"line three")
            await pilot.pause()
            assert len(captured) == count
            assert prompt.text == "line one\nline two\nline three"
            await pilot.press("enter")
            await pilot.pause()
            assert len(captured) == count + 1
            assert captured[-1].body == "line one\nline two\nline three"
            await pilot.press("!")
            await pilot.pause()
            assert not prompt.shell_mode and prompt.text == "!"
            assert not prompt.show_path_search
            prompt.text = ""
            area.post_message(area.RequestShellMode())
            await pilot.pause()
            assert prompt.shell_mode and not prompt.text
            await pilot.press("p", "w", "d", "enter")
            await pilot.pause()
            assert captured[-1].shell and captured[-1].body == "pwd"
            assert not prompt.shell_mode and not area.shell_mode
            await pilot.press(*"open", "space", *"again", "enter")
            await pilot.pause()
            assert captured[-1].body == "open again" and not captured[-1].shell
    print("prompt routing: command prefixes remain agent input; explicit shell is one-shot")


if __name__ == "__main__":
    asyncio.run(main())
