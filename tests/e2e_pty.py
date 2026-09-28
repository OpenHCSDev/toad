"""Shared explicit-launch PTY fixture for installed Toad terminal tests."""

import asyncio
import atexit
import json
import os
import signal
import sys
import time
from pathlib import Path
from dataclasses import dataclass
from collections.abc import Mapping

import pyte
from runtime_fixture import stop_test_owners

FORK_ROOT = Path(__file__).resolve().parents[1]
FORK_TOAD = FORK_ROOT / ".venv" / "bin" / "toad"
AGENT_PY = FORK_ROOT / ".venv" / "bin" / "python"


def sgr_click(x: int, y: int, button: int = 0) -> bytes:
    return f"\x1b[<{button};{x};{y}M".encode() + f"\x1b[<{button};{x};{y}m".encode()


SCREEN_H = 40
SCREEN_W = 120


@dataclass(frozen=True)
class PtyLaunch:
    command: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]


class ToadSession:
    """Real toad on a fixed-size pty: the screen is always the last
    SCREEN_H lines of the output buffer."""

    def __init__(self, launch: PtyLaunch) -> None:
        self.launch = launch
        self.proc = None
        self.master = None
        self.buffer = b""
        self.last_screen_lines: list[str] = []
        self.terminal = pyte.Screen(SCREEN_W, SCREEN_H)
        self.stream = pyte.Stream(self.terminal)
        atexit.register(self.close)

    def close(self) -> None:
        if self.alive() and self.proc is not None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        root = Path(self.launch.environment["AGENT_COMMS_ROOT"])
        if root.exists():
            stop_test_owners(root)

    async def stop(self) -> None:
        """Reap the isolated UI and its servers before removing their temporary wire."""
        import psutil

        if self.proc is None or self.proc.returncode is not None:
            return
        children = psutil.Process(self.proc.pid).children(recursive=True)
        self.proc.terminate()
        try:
            await asyncio.wait_for(self.proc.wait(), 5)
        except TimeoutError:
            self.close()
            await self.proc.wait()
        _, alive = await asyncio.to_thread(psutil.wait_procs, children, timeout=5)
        for child in alive:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        await asyncio.to_thread(psutil.wait_procs, alive, timeout=5)
        root = Path(self.launch.environment["AGENT_COMMS_ROOT"])
        await asyncio.to_thread(stop_test_owners, root)

    async def start(self) -> None:
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()
        winsize = struct.pack("HHHH", SCREEN_H, SCREEN_W, 0, 0)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)
        self.master = master
        env = dict(os.environ, TERM="xterm-256color")
        env.update(self.launch.environment)
        self.proc = await asyncio.create_subprocess_exec(
            *self.launch.command,
            cwd=str(self.launch.cwd),
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        os.set_blocking(master, False)
        await asyncio.sleep(6)

    def _screen(self) -> str:
        self._drain()
        return "\n".join(self.terminal.display)

    def _set_size(self, h: int, w: int) -> None:
        import fcntl
        import struct
        import termios

        self._drain()
        self.terminal.resize(lines=h, columns=w)
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", h, w, 0, 0))
        # This harness uses start_new_session without claiming a controlling TTY,
        # so the kernel has no foreground process group to notify automatically.
        if self.proc is not None:
            os.kill(self.proc.pid, signal.SIGWINCH)

    def _drain(self) -> None:
        import select

        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            ready, _, _ = select.select([self.master], [], [], 0)
            if not ready:
                break
            try:
                chunk = os.read(self.master, 262144)
            except BlockingIOError, OSError:
                break
            if not chunk:
                break
            self.buffer += chunk
            self.stream.feed(chunk.decode("utf-8", "replace"))

    def screen_lines(self) -> list[str]:
        return self._screen().splitlines()

    async def send(self, data: bytes) -> None:
        assert self.master is not None
        os.write(self.master, data)

    async def read_available(self, seconds: float = 1.5) -> str:
        await asyncio.sleep(seconds)
        return self._screen()

    async def frame(self, seconds: float = 1.5) -> str:
        await asyncio.sleep(seconds)
        return self._screen()

    async def next_output(self, timeout: float = 3) -> str:
        """Parse the next real PTY write without a timed polling interval."""
        assert self.master is not None
        readable = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop.add_reader(self.master, readable.set)
        try:
            await asyncio.wait_for(readable.wait(), timeout)
        finally:
            loop.remove_reader(self.master)
        return self._screen()

    async def click(self, x: int, y: int, button: int = 0) -> None:
        await self.send(sgr_click(x, y, button))

    async def click_row(self, name: str, button: int = 0, occurrence: int = 0) -> bool:
        """Parse the CURRENT screen (fixed-size pty), find the row, click."""
        await asyncio.sleep(0.4)
        lines = self.screen_lines()
        self.last_screen_lines = lines
        matches = [
            index
            for index, line in enumerate(lines)
            if self._is_row(line.split("▎", 1)[0].strip(), name)
        ]
        if len(matches) <= occurrence:
            return False
        index = matches[occurrence]
        await self.click(6, index + 1, button)
        return True

    async def click_text(self, text: str, *, last: bool = False, button: int = 0) -> bool:
        """Click the first visible occurrence of text at its rendered position."""
        await asyncio.sleep(0.2)
        lines = list(enumerate(self.screen_lines()))
        for index, line in reversed(lines) if last else lines:
            column = line.find(text)
            if column >= 0:
                await self.click(column + 1, index + 1, button)
                return True
        return False

    @staticmethod
    def _is_row(stripped: str, name: str) -> bool:
        return (
            stripped == name
            or stripped.startswith(f"{name} ")
            or (
                stripped.startswith(("●", "✓", "?", "⌛"))
                and name in stripped
                and len(stripped) < 45
            )
            or (
                stripped.startswith(("○", "▶", "▸", "▾"))
                and name in stripped
                and len(stripped) < 45
            )
        )

    async def type_text(self, text: str) -> None:
        await self.send(text.encode())

    async def press_enter(self) -> None:
        await self.send(b"\r")

    async def key(self, k: str) -> None:
        await self.send(k.encode())

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None
