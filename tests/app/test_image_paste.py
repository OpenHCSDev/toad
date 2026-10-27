"""Ctrl+V captures a clipboard PNG without blocking typing, keeps it private, and falls back to pasted text."""

import asyncio
import base64
import shutil
from support.clipboard import ClipboardProcess
from pathlib import Path
from unittest.mock import patch

from toad.prompt.extract import extract_paths_from_prompt

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDqkAAAAASUVORK5CYII="


async def test_pasting_an_image_keeps_typing_responsive_and_stores_a_private_file(workspace, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(workspace.roots.attempt / "data with spaces"))
    async with workspace.app() as ui:
        started = asyncio.Event()
        process = ClipboardProcess()
        actual_spawn, actual_which = asyncio.create_subprocess_exec, shutil.which
        monkeypatch.setenv("DISPLAY", ":clipboard-test")
        monkeypatch.setenv("WAYLAND_DISPLAY", "")

        async def spawn(*command, **kwargs):
            if command == ("xclip", "-selection", "clipboard", "-t", "image/png", "-o"):
                started.set()
                return process
            return await actual_spawn(*command, **kwargs)

        def which(command, *args, **kwargs):
            return "/usr/bin/xclip" if command == "xclip" else actual_which(command, *args, **kwargs)

        with patch("asyncio.create_subprocess_exec", spawn), patch("shutil.which", which):
            await ui.write_draft("")
            await ui.press("ctrl+v")
            await asyncio.wait_for(started.wait(), 3)
            await ui.type("Inspect image")
            assert ui.draft() == "Inspect image"
            process.emit(base64.b64decode(PNG))
            await ui.until(lambda: "clipboard-" in ui.draft(), why="the image reference in the draft")
            assert len(list(extract_paths_from_prompt(ui.draft()))) == 1, ui.draft()
            attachment = Path(next(extract_paths_from_prompt(ui.draft()))[0])
            assert attachment.read_bytes() == base64.b64decode(PNG)
            assert attachment.stat().st_mode & 0o777 == 0o600
