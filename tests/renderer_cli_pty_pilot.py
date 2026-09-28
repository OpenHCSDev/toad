"""Actual installed CLI/terminal startup and configured backends; no model calls."""

import asyncio
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time

from platformdirs import user_runtime_path
from toad.render_service import RenderServiceConfig
from toad.render_zmq import RendererEndpoint, PersistentRendererPool


def launch(directory, options, settings, runtime):
    environment = dict(os.environ)
    for key in ("AGENT_COMMS_THREAD", "PI_AGENT_ID", "PI_PROMPT", "TOAD_RENDERER"):
        environment.pop(key, None)
    for key, name in [
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_DATA_HOME", "data"),
    ]:
        environment[key] = str(directory / name)
    environment["XDG_RUNTIME_DIR"] = str(runtime / directory.name)
    Path(environment["XDG_RUNTIME_DIR"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    environment["AGENT_COMMS_ROOT"] = str(directory / "wire")
    environment["TERM"] = "xterm-256color"
    environment["COLUMNS"] = "100"
    environment["LINES"] = "30"
    config = directory / "config" / "toad"
    config.mkdir(parents=True)
    (config / "toad.json").write_text(json.dumps({"ui": {"renderer": settings}}))
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    process = subprocess.Popen(
        [
            str(Path(sys.executable).parent / "toad"),
            "run",
            "--agent",
            "",
            *options,
            str(directory),
        ],
        env=environment,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    chunks = []
    started = time.monotonic()
    sent = False
    try:
        while process.poll() is None and time.monotonic() - started < 12:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    chunks.append(os.read(master, 65536))
                except OSError:
                    break
            if not sent and time.monotonic() - started > 4:
                os.write(master, b"\x11")
                sent = True
        result = process.wait(timeout=4)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=4)
        os.close(master)
    text = b"".join(chunks).decode("utf-8", "replace")
    (
        Path(__file__).parents[1] / "evidence/t6" / f"cli-{directory.name}-terminal.txt"
    ).write_text(text)
    assert result == 0, (result, text[-3000:])
    assert "Traceback" not in text, text[-3000:]
    assert "\x1b[" in text, "CLI did not present terminal frames"
    return environment, len(text)


async def main():
    with (
        tempfile.TemporaryDirectory(prefix="rcli-") as temporary,
        tempfile.TemporaryDirectory(prefix="rc-") as runtime,
    ):
        base = Path(temporary)
        for name, options, saved in [
            ("local", ["--renderer", "local"], "local"),
            ("persistent", [], "persistent"),
        ]:
            directory = base / name
            directory.mkdir()
            environment, size = await asyncio.to_thread(
                launch, directory, options, saved, Path(runtime)
            )
            if name == "persistent":
                previous = os.environ.get("XDG_RUNTIME_DIR")
                os.environ["XDG_RUNTIME_DIR"] = environment["XDG_RUNTIME_DIR"]
                try:
                    endpoint = await asyncio.to_thread(
                        RendererEndpoint.for_runtime,
                        user_runtime_path("toad-renderer"),
                        RenderServiceConfig(),
                    )
                    pool = PersistentRendererPool(endpoint)
                    try:
                        assert await pool.shutdown_service()
                    finally:
                        await pool.aclose()
                finally:
                    if previous is None:
                        os.environ.pop("XDG_RUNTIME_DIR", None)
                    else:
                        os.environ["XDG_RUNTIME_DIR"] = previous
            print(
                {
                    "actual_cli_backend": name,
                    "saved_choice_used": not options,
                    "terminal_characters": size,
                    "exit": 0,
                }
            )


if __name__ == "__main__":
    asyncio.run(main())
