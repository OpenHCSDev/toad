"""Ctrl+V captures a private PNG without blocking input, and retains text paste."""

import asyncio
import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.prompt.extract import extract_paths_from_prompt

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDqkAAAAASUVORK5CYII="


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-image-paste-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data with spaces"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = app.selected_session.conversation
            started, release = asyncio.Event(), asyncio.Event()

            async def clipboard_image():
                started.set()
                await release.wait()
                return base64.b64decode(PNG)

            with patch("toad.clipboard_image.read_clipboard_png", clipboard_image):
                view.prompt.focus()
                await pilot.press("ctrl+v")
                await asyncio.wait_for(started.wait(), 3)
                await pilot.press(*"Inspect image")
                assert view.prompt.text == "Inspect image"
                release.set()
                await until(lambda: "clipboard-" in view.prompt.text)
                assert len(list(extract_paths_from_prompt(view.prompt.text))) == 1, view.prompt.text
                reference = next(extract_paths_from_prompt(view.prompt.text))[0]
                attachment = Path(reference)
                assert attachment.read_bytes() == base64.b64decode(PNG)
                assert attachment.stat().st_mode & 0o777 == 0o600
            async def no_image():
                return None
            with patch("toad.clipboard_image.read_clipboard_png", no_image), patch("pyperclip.paste", return_value="first\nsecond"):
                view.prompt.text = ""
                view.prompt.focus()
                await pilot.press("ctrl+v")
                await until(lambda: view.prompt.text == "first\nsecond")

    print("image paste: responsive capture, private retained attachment and text fallback")


if __name__ == "__main__":
    asyncio.run(main())
