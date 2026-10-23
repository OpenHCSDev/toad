"""Toad running in a real pseudo-terminal, read through a terminal emulator.

The process writes exactly what it would write to a user's terminal; the
emulator (pyte, from the ``terminal_emulator`` fixture) turns those bytes into
the screen a user would see. Tests ask this class what is shown and send it
the bytes a terminal would send.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import fcntl
import os
from pathlib import Path
import pty
import signal
import struct
import sys
import termios

TOAD = Path(sys.executable).with_name("toad")


def toad_command(*arguments: str) -> tuple[str, ...]:
    """The ``toad`` entry point installed next to the running interpreter, run by that interpreter."""
    return (sys.executable, str(TOAD), *arguments)


class NotShown(AssertionError):
    """The terminal never showed what the test waited for; carries the last screen."""


class Terminal:
    """One process on a pseudo-terminal of a fixed size."""

    def __init__(self, emulator, workspace, rows: int, columns: int) -> None:
        self.workspace = workspace
        self.screen = emulator.Screen(columns, rows)
        self._stream = emulator.Stream(self.screen)
        self.rows, self.columns = rows, columns
        self.output = b""
        self.process: asyncio.subprocess.Process | None = None
        self._master: int | None = None

    async def start(self, command: tuple[str, ...], *, environment: dict[str, str] | None = None) -> None:
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.columns, 0, 0))
        env = self.workspace.roots.environment(dict(os.environ)) | (environment or {})
        env["PYTHONPATH"] = os.pathsep.join(str(Path(path).absolute()) for path in sys.path)
        self._master = master
        self.process = await asyncio.create_subprocess_exec(
            *command, cwd=str(self.workspace.project), env=env,
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        os.set_blocking(master, False)
        asyncio.get_running_loop().add_reader(master, self._read)

    def _read(self) -> None:
        try:
            chunk = os.read(self._master, 262144)
        except (BlockingIOError, OSError):
            chunk = b""
        if not chunk:
            asyncio.get_running_loop().remove_reader(self._master)
            return
        self.output += chunk
        self._stream.feed(chunk.decode("utf-8", "replace"))

    @property
    def returncode(self) -> int | None:
        return self.process.returncode

    def lines(self) -> list[str]:
        """The text of every row of the screen, top to bottom."""
        return list(self.screen.display)

    def text(self) -> str:
        return "\n".join(self.lines())

    def shows(self, text: str) -> bool:
        return text in self.text()

    async def send(self, data: bytes | str) -> None:
        os.write(self._master, data.encode() if isinstance(data, str) else data)

    async def click(self, x: int, y: int, button: int = 0) -> None:
        """A press and release at the 1-based cell (x, y), as a terminal reports mouse clicks."""
        await self.send(f"\x1b[<{button};{x};{y}M\x1b[<{button};{x};{y}m")

    async def click_text(self, text: str) -> None:
        """Click the first cell of `text` where it is shown."""
        for row, line in enumerate(self.lines()):
            if (column := line.find(text)) >= 0:
                await self.click(column + 1, row + 1)
                return
        raise NotShown(f"{text!r} is not on screen:\n{self.text()}")

    async def until(self, condition, *, seconds: float = 15, why: str = "") -> None:
        """Wait until `condition()` is true; fails with the screen if the process ends first."""
        try:
            async with asyncio.timeout(seconds):
                while not condition():
                    if self.returncode is not None:
                        raise NotShown(f"the process exited ({self.returncode}) before {why or 'the condition'}; "
                                       f"screen:\n{self.text()}")
                    await asyncio.sleep(0.02)
        except TimeoutError:
            raise NotShown(f"{why or 'condition'} not reached in {seconds}s; screen:\n{self.text()}") from None

    async def until_shows(self, text: str, *, seconds: float = 15) -> None:
        await self.until(lambda: self.shows(text), seconds=seconds, why=f"{text!r} on screen")

    async def until_exit(self, *, seconds: float = 10) -> int:
        try:
            async with asyncio.timeout(seconds):
                return await self.process.wait()
        except TimeoutError:
            raise NotShown(f"the process did not exit in {seconds}s; screen:\n{self.text()}") from None

    async def resize(self, rows: int, columns: int) -> None:
        self.rows, self.columns = rows, columns
        self.screen.resize(lines=rows, columns=columns)
        fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        # The process has no controlling terminal, so the kernel does not notify it.
        os.kill(self.process.pid, signal.SIGWINCH)

    async def stop(self) -> None:
        """End the process and what it started (the roots' leftovers are stopped by the runner)."""
        if self.process is not None and self.process.returncode is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                async with asyncio.timeout(5):
                    await self.process.wait()
            except TimeoutError:
                os.killpg(self.process.pid, signal.SIGKILL)
                await self.process.wait()
            except ProcessLookupError:
                pass
        if self._master is not None:
            asyncio.get_running_loop().remove_reader(self._master)
            os.close(self._master)
            self._master = None


@asynccontextmanager
async def terminal_running(workspace, emulator, command: tuple[str, ...], *, size: tuple[int, int] = (40, 120),
                            environment: dict[str, str] | None = None):
    """Start `command` on a pseudo-terminal of `size` (rows, columns) and stop it afterwards."""
    terminal = Terminal(emulator, workspace, *size)
    await terminal.start(command, environment=environment)
    try:
        yield terminal
    except BaseException:
        print(terminal.output.decode(errors="replace")[-4000:], flush=True)
        raise
    finally:
        await terminal.stop()
