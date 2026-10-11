"""Image references in a prompt become image blocks; the clipboard image is read within a bound."""

import asyncio
import base64
from unittest.mock import patch

import pytest

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


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "private data"))
    (tmp_path / "project").mkdir()
    return tmp_path / "project"


def test_quoted_image_references_become_image_blocks_after_the_text(project):
    (project / "image one.png").write_bytes(PNG)
    (project / "image two.png").write_bytes(PNG)
    prompt = '@"image one.png" inspect both @"image two.png"'
    assert [name for name, _, _ in extract_paths_from_prompt(prompt)] == ["image one.png", "image two.png"]
    content = build(project, prompt)
    assert content[0].text == "inspect both"
    assert len(content) == 3 and all(block.type == "image" for block in content[1:])
    assert all(base64.b64decode(block.data) == PNG for block in content[1:])


def test_a_saved_clipboard_image_is_cached_once_and_referenced_as_an_image(project):
    cached = clipboard_image.save_clipboard_png(PNG)
    assert clipboard_image.save_clipboard_png(PNG) == cached
    assert len(build(project, f'@"{cached}"')) == 2


@pytest.mark.parametrize("reference", ["@missing.png", "@../outside.png"])
def test_a_missing_or_out_of_scope_image_is_refused(project, reference):
    (project.parent / "outside.png").write_bytes(PNG)
    with pytest.raises(ValueError):
        build(project, reference)


async def test_clipboard_image_read_returns_the_bytes_and_stops_at_the_size_bound(monkeypatch):
    data = PNG + b"x" * 100000
    process = Process(data)

    async def spawn(*command, **kwargs):
        assert command == ("xclip", "-selection", "clipboard", "-t", "image/png", "-o")
        return process

    monkeypatch.setenv("DISPLAY", ":test")
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    with patch("toad.clipboard_image.shutil.which", return_value="/usr/bin/xclip"), patch(
            "toad.clipboard_image.asyncio.create_subprocess_exec", spawn):
        assert await clipboard_image.read_clipboard_png() == data
        assert not process.killed
        process = Process(data)
        with patch("toad.clipboard_image.MAX_IMAGE_BYTES", 128):
            with pytest.raises(ValueError):
                await clipboard_image.read_clipboard_png()
            assert process.killed and process.returncode == -9
