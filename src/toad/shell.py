from __future__ import annotations

import asyncio
import codecs
import fcntl
import os
import platform
import pty
import struct
import termios
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual import log
from textual.message import Message

from toad.shell_read import shell_read
from toad.terminal_environment import TerminalEnvironment
from toad import ansi
from toad.shell_output import ShellCommandOutput, ShellTerminalOutput
from toad.shell_source import ShellOperationalSource

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation

IS_MACOS = platform.system() == "Darwin"


def resize_pty(fd, cols, rows):
    """Resize the pseudo-terminal"""
    # Pack the dimensions into the format expected by TIOCSWINSZ
    try:
        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
    except OSError:
        # Possibly file descriptor closed
        pass


@dataclass
class CurrentWorkingDirectoryChanged(Message):
    """Current working directory has changed in shell."""

    path: str


@dataclass
class ShellFinished(Message):
    """The shell finished."""


class Shell(ShellOperationalSource):
    """Responsible for shell interactions in Conversation."""

    def __init__(
        self,
        conversation: Conversation,
        working_directory: str,
        shell="",
        start="",
        hide_start: bool = True,
    ) -> None:
        super().__init__(conversation)
        self.working_directory = working_directory

        self.new_log: bool = False
        self.shell = shell
        self.shell_start = start
        self.hide_start = hide_start

        self._ready_event: asyncio.Event = asyncio.Event()

        self._hide_echo: set[bytes] = set()
        """A set of byte strings to remove from output."""

        self._hide_output = hide_start
        self._pending_directory: str | None = None
        """Hide all output."""

        self._pid: int | None = None
        """Shell process id"""

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def pending_directory(self) -> str | None:
        return self._pending_directory

    def _is_busy(self) -> bool:
        """Check if the shell is busy.

        Called from a thread by `is_busy`.

        Returns:
            `True` if a command is running, or `False` if the shell is waiting for input.

        """
        if self._pid is None:
            return False
        import psutil

        try:
            shell_process = psutil.Process(self._pid)
            children = shell_process.children(recursive=True)
        except psutil.NoSuchProcess, psutil.AccessDenied:
            return False
        else:
            return bool(children)

    async def is_busy(self) -> bool:
        """Is there a process running in the shell?

        Returns:
            `True` if a command is running, or `False` if the shell is waiting for input.
        """
        return await asyncio.to_thread(self._is_busy)

    async def wait_for_ready(self) -> None:
        await self._ready_event.wait()

    async def send(self, command: str, width: int, height: int) -> None:
        await self._ready_event.wait()
        self._terminal_size = width, height
        if self.master is None:
            print("TTY FD not set")
            return

        if self.output is not None:
            self.output.finalize()
            self.output = None
        command_output = ShellCommandOutput(command)
        self.outputs.append(command_output)
        await self._present(command_output)

        try:
            await asyncio.to_thread(resize_pty, self.master, width, max(height, 1))
        except OSError:
            pass

        if self._pending_directory is not None:
            import shlex

            command = (
                f"cd -- {shlex.quote(self._pending_directory)} && {{\n{command}\n}}"
            )
        get_pwd_command = f"{command};" + r'printf "\e]2025;$(pwd);\e\\"' + "\n"
        await self.write(get_pwd_command, hide_echo=True)

    async def change_directory(self, path: str) -> None:
        """Move an idle shell now, or apply the change before its next command."""
        import shlex

        self.working_directory = path
        self._pending_directory = path
        await self.wait_for_ready()
        if not await self.is_busy():
            await self.write(
                f"cd -- {shlex.quote(path)};" + r'printf "\e]2025;$(pwd);\e\\"' + "\n",
                hide_echo=True,
                hide_output=True,
            )

    async def send_input(self, text: str, paste: bool = False) -> None:
        await self._ready_event.wait()
        if self.master is None:
            return
        if paste and self.output is not None and self.output.state.bracketed_paste:
            text = f"\x1b[200~{text}\x1b[201~"
        await self.write(f"{text}\n", hide_echo=True)

    def start(self) -> None:
        assert self._task is None
        self._task = asyncio.create_task(self.run(), name=repr(self))
        log("shell starting")

    async def interrupt(self) -> None:
        """Interrupt the running command."""
        await self.write(b"\x03")

    def update_size(self, width: int, height: int) -> None:
        """Update the size of the shell pty.

        Args:
            width: Desired width.
            height: Desired height.
        """
        self._terminal_size = width, height
        if self.output is not None:
            self.output.state.update_size(width, height)
        if self.master is None:
            return
        with suppress(OSError):
            resize_pty(self.master, width, max(height, 1))

    async def write(
        self, text: str | bytes, hide_echo: bool = False, hide_output: bool = False
    ) -> int:
        if self.master is None:
            return 0
        text_bytes = text.encode("utf-8", "ignore") if isinstance(text, str) else text

        if hide_echo:
            for line in text_bytes.split(b"\n"):
                if line:
                    self._hide_echo.add(line)
        try:
            result = await asyncio.to_thread(os.write, self.master, text_bytes)
        except OSError:
            return 0
        self._hide_output = hide_output
        return result

    async def _run_pty(self) -> None:
        current_directory = self.working_directory

        master, slave = pty.openpty()
        self.master = master

        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        env = TerminalEnvironment.for_child(os.environ)

        shell = self.shell or TerminalEnvironment.login_shell(env)

        def setup_pty():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        try:
            _process = await asyncio.create_subprocess_shell(
                shell,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                cwd=current_directory,
                preexec_fn=setup_pty,
            )
        except Exception as error:
            os.close(slave)
            self._app.notify(
                f"Unable to start shell: {error}\n\nCheck your settings.",
                title="Shell",
                severity="error",
            )
            return
        self._process = _process
        self._pid = _process.pid

        os.close(slave)
        BUFFER_SIZE = 64 * 1024
        reader = asyncio.StreamReader(BUFFER_SIZE)
        protocol = asyncio.StreamReaderProtocol(reader)

        loop = asyncio.get_event_loop()
        transport, _ = await loop.connect_read_pipe(
            lambda: protocol, os.fdopen(master, "rb", 0)
        )

        self._transport = transport
        self._ready_event.set()

        if shell_start := self.shell_start.strip():
            shell_start = self.shell_start.strip()
            if not shell_start.endswith("\n"):
                shell_start += "\n"
            await self.write(shell_start, hide_echo=False, hide_output=self.hide_start)

        unicode_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        while True:
            data = await shell_read(reader, BUFFER_SIZE)

            for string_bytes in list(self._hide_echo):
                remove_bytes = string_bytes
                if remove_bytes in data:
                    remove_start = data.index(remove_bytes)
                    try:
                        next_line = data.index(b"\n", remove_start + len(remove_bytes))
                    except ValueError:
                        data = data.replace(remove_bytes, b"\x1b[2K")
                    else:
                        data = data[:remove_start] + b"\x1b[2K" + data[next_line + 1 :]

                    self._hide_echo.discard(string_bytes)

            if line := unicode_decoder.decode(data, final=not data):
                if self.output is None or self.output.finalized:
                    self.output = ShellTerminalOutput(ansi.TerminalState(
                        self.write, width=self._terminal_size[0], height=self._terminal_size[1]
                    ))
                    self.outputs.append(self.output)
                output = self.output
                scrollback, alternate = await output.state.write(
                    line, hide_output=self._hide_output
                )
                new_directory = output.state.current_directory
                if new_directory:
                    output.finalized = True
                await self._present(output)
                output.project(scrollback, alternate)
                if new_directory == self._pending_directory:
                    self._pending_directory = None
                if new_directory and new_directory != current_directory:
                    current_directory = self.working_directory = new_directory
                    if (conversation := self._conversation()) is not None:
                        conversation.post_message(CurrentWorkingDirectoryChanged(new_directory))
                if output.finalized and output.state.scrollback_buffer.is_blank:
                    output.finalize()
                    self.outputs.remove(output)
                    self.output = None

            if not data:
                break

        self.master = None
        self._finished = True
        transport.close()
        if (conversation := self._conversation()) is not None:
            conversation.post_message(ShellFinished())
