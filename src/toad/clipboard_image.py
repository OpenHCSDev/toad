"""Non-blocking native clipboard PNG capture for terminal image attachments."""

import asyncio
import hashlib
import os
from pathlib import Path
import shutil

from agent_comms.image_inputs import MAX_IMAGE_BYTES
from toad import paths

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def attachment_directory() -> Path:
    return paths.get_data() / "clipboard-images"


async def read_clipboard_png() -> bytes | None:
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        command = ["wl-paste", "--type", "image/png"]
    elif os.environ.get("DISPLAY") and shutil.which("xclip"):
        command = ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"]
    else:
        return None
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        async with asyncio.timeout(3):
            chunks = []
            size = 0
            while chunk := await process.stdout.read(65536):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    raise ValueError("Clipboard image exceeds the 4 MiB attachment limit.")
                chunks.append(chunk)
            data = b"".join(chunks)
            if await process.wait() != 0 or not data:
                return None
        if not data.startswith(PNG_SIGNATURE):
            raise ValueError("The clipboard did not return a PNG image.")
        return data
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def save_clipboard_png(data: bytes) -> Path:
    if not data.startswith(PNG_SIGNATURE) or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Invalid or oversized clipboard PNG.")
    folder = attachment_directory()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / f"clipboard-{hashlib.sha256(data).hexdigest()}.png"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError("Clipboard attachment cache entry is inconsistent.")
    else:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
    return path
