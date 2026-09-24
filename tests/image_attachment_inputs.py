"""Bounded clipboard transport and image-reference preparation contracts."""

import asyncio
import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from toad import clipboard_image
from toad.acp.prompt import build
from toad.prompt.extract import extract_paths_from_prompt

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDqkAAAAASUVORK5CYII=")


class Process:
    def __init__(self, data):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(data)
        self.stdout.feed_eof()
        self.returncode = None
        self.killed = False

    async def wait(self):
        self.returncode = -9 if self.killed else 0
        return self.returncode

    def kill(self):
        self.killed = True


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-image-input-") as directory:
        root = Path(directory)
        os.environ["XDG_DATA_HOME"] = str(root / "private data")
        project = root / "project"
        project.mkdir()
        first = project / "image one.png"
        second = project / "image two.png"
        first.write_bytes(PNG)
        second.write_bytes(PNG)
        prompt = '@"image one.png" inspect both @"image two.png"'
        assert [name for name, _, _ in extract_paths_from_prompt(prompt)] == ["image one.png", "image two.png"]
        content = build(project, prompt)
        assert content[0]["text"] == "inspect both"
        assert len(content) == 3 and all(block["type"] == "image" for block in content[1:])
        assert all(base64.b64decode(block["data"]) == PNG for block in content[1:])
        cached = clipboard_image.save_clipboard_png(PNG)
        assert clipboard_image.save_clipboard_png(PNG) == cached
        assert len(build(project, f'@"{cached}"')) == 2
        outside = root / "outside.png"
        outside.write_bytes(PNG)
        for reference in ("@missing.png", "@../outside.png"):
            try:
                build(project, reference)
            except ValueError:
                pass
            else:
                raise AssertionError("Missing/out-of-scope image was silently accepted")
        data = PNG + b"x" * 100000
        process = Process(data)

        async def spawn(*command, **kwargs):
            assert command == ("xclip", "-selection", "clipboard", "-t", "image/png", "-o")
            return process

        with patch.dict(os.environ, {"DISPLAY": ":test", "WAYLAND_DISPLAY": ""}), patch(
            "toad.clipboard_image.shutil.which", return_value="/usr/bin/xclip"
        ), patch("toad.clipboard_image.asyncio.create_subprocess_exec", spawn):
            assert await clipboard_image.read_clipboard_png() == data
            assert not process.killed
            process = Process(data)
            with patch("toad.clipboard_image.MAX_IMAGE_BYTES", 128):
                try:
                    await clipboard_image.read_clipboard_png()
                except ValueError:
                    pass
                else:
                    raise AssertionError("Oversized clipboard image was accepted")
                assert process.killed and process.returncode == -9
    print("image inputs: quoted references, PNG bytes, private cache, explicit errors, bounded clipboard reads")


if __name__ == "__main__":
    asyncio.run(main())
