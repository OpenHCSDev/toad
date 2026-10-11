"""Ctrl+V captures a clipboard PNG without blocking typing, keeps it private, and falls back to pasted text."""

import asyncio
import base64
from pathlib import Path
from unittest.mock import patch

from toad.prompt.extract import extract_paths_from_prompt

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDqkAAAAASUVORK5CYII="


async def test_pasting_an_image_keeps_typing_responsive_and_stores_a_private_file(workspace, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(workspace.roots.attempt / "data with spaces"))
    async with workspace.app() as ui:
        started, release = asyncio.Event(), asyncio.Event()

        async def clipboard_image():
            started.set()
            await release.wait()
            return base64.b64decode(PNG)

        with patch("toad.clipboard_image.read_clipboard_png", clipboard_image):
            await ui.write_draft("")
            await ui.press("ctrl+v")
            await asyncio.wait_for(started.wait(), 3)
            await ui.type("Inspect image")
            assert ui.draft() == "Inspect image"
            release.set()
            await ui.until(lambda: "clipboard-" in ui.draft(), why="the image reference in the draft")
            assert len(list(extract_paths_from_prompt(ui.draft()))) == 1, ui.draft()
            attachment = Path(next(extract_paths_from_prompt(ui.draft()))[0])
            assert attachment.read_bytes() == base64.b64decode(PNG)
            assert attachment.stat().st_mode & 0o777 == 0o600
