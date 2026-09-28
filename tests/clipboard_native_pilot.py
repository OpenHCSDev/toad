"""Real private X11 selection and actual PTY OSC52; no mocked copy/driver."""

import base64
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

import psutil
from tab_clipboard_native_app import PAYLOAD

from toad.clipboard import SystemClipboard, TerminalClipboard


def copy_in_terminal(root, display):
    root.mkdir()
    env = {
        **os.environ,
        "AGENT_COMMS_ROOT": str(root / "wire"),
        "PI_CODING_AGENT_DIR": str(root / "pi"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_STATE_HOME": str(root / "state"),
        "XDG_DATA_HOME": str(root / "data"),
        "TERM": "xterm-256color",
    }
    for name in (
        "PYTHONPATH",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "AGENT_COMMS_THREAD",
        "PI_PROMPT",
    ):
        env.pop(name, None)
    if display is not None:
        env["DISPLAY"] = display
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 110, 0, 0))
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).with_name("tab_clipboard_native_app.py")),
            str(root),
        ],
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    output = bytearray()
    sent = False
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                output.extend(chunk)
            if not sent and (root / "ready.json").exists():
                os.write(master, b"\x19")
                sent = True
            if (
                process.poll() is not None
                and not select.select([master], [], [], 0.05)[0]
            ):
                break
        assert sent and process.wait(timeout=3) == 0, output[-3000:]
        copied = json.loads((root / "copied.json").read_text())
        assert copied["complete_local_value"] and copied["length"] == len(PAYLOAD)
        ready = json.loads((root / "ready.json").read_text())
        assert "site-packages" in ready["installed"], ready
        sequences = re.findall(rb"\x1b\]52;c;([^\x07]*)\x07", output)
        if display is not None:
            assert ready["transport"] == SystemClipboard.declared_name
            assert not sequences, (
                "Native success also emitted a truncatable terminal copy"
            )
            read = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                env=env,
                capture_output=True,
                timeout=3,
                check=True,
            )
            assert read.stdout.decode() == PAYLOAD
        else:
            assert ready["transport"] == TerminalClipboard.declared_name
            assert (
                len(sequences) == 1
                and base64.b64decode(sequences[0]).decode() == PAYLOAD
            )
        return {
            "transport": ready["transport"],
            "length": copied["length"],
            "physical_input": True,
            "terminal_sequences": len(sequences),
        }
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        os.close(master)
        for child in psutil.process_iter():
            try:
                if child.environ().get("AGENT_COMMS_ROOT") == str(root / "wire"):
                    child.terminate()
                    child.wait(timeout=3)
            except psutil.NoSuchProcess, psutil.AccessDenied:
                pass


def main():
    with tempfile.TemporaryDirectory(prefix="cp-", dir="/home/ts/wt") as directory:
        root = Path(directory)
        reader, writer = os.pipe()
        server = subprocess.Popen(
            [
                "Xvfb",
                "-displayfd",
                str(writer),
                "-screen",
                "0",
                "1100x740x24",
                "-nolisten",
                "tcp",
            ],
            pass_fds=(writer,),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        os.close(writer)
        try:
            assert select.select([reader], [], [], 5)[0], "Private X11 did not start"
            display = ":" + os.read(reader, 32).decode().strip()
            proof = [
                copy_in_terminal(root / "system", display),
                copy_in_terminal(root / "terminal", None),
            ]
            print(
                json.dumps(
                    {
                        "proof": proof,
                        "boundary": "installed Toad/LinuxDriver + private X11/xclip + PTY",
                        "mocks": False,
                    }
                )
            )
        finally:
            os.close(reader)
            server.terminate()
            server.wait(timeout=3)


if __name__ == "__main__":
    main()
